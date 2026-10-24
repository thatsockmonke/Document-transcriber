"""A project-scoped rule builder and a separate, undoable change-review flow."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .rules import TEMPLATES, new_rule, preview_rules, validate_rules


def hint(text):
    widget = QLabel(text)
    widget.setObjectName("muted")
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget


def action(text, callback, primary=False):
    button = QPushButton(text)
    if primary:
        button.setObjectName("primary")
    button.clicked.connect(callback)
    return button


def highlight_changes(editor, spans):
    selections = []
    text = editor.toPlainText()
    for start, end in spans:
        selection = QTextEdit.ExtraSelection()
        selection.cursor = editor.textCursor()
        selection.cursor.setPosition(len(text[:start].encode("utf-16-le")) // 2)
        selection.cursor.setPosition(
            len(text[:end].encode("utf-16-le")) // 2, QTextCursor.KeepAnchor
        )
        selection.format = QTextCharFormat()
        selection.format.setBackground(QColor("#62432c"))
        selection.format.setForeground(QColor("#ffd5b7"))
        selections.append(selection)
    editor.setExtraSelections(selections)


class RulesDialog(QDialog):
    def __init__(self, rules, sample="", parent=None, review_on_export=True):
        super().__init__(parent)
        self.setWindowTitle("Writing rules · This project")
        self.resize(960, 740)
        self.setMinimumSize(780, 600)
        self.rules = validate_rules([rule.to_dict() for rule in rules])
        self.loading = False
        self.selected_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)
        title = QLabel("WRITING RULES")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(
            hint(
                "Choose how this project should read. Enable a rule, edit its settings, "
                "and test it below. Saving rules does not change your transcription."
            )
        )
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 14, 0)
        ll.addWidget(hint("RULES RUN IN THE ORDER SHOWN"))
        self.rule_list = QListWidget()
        self.rule_list.currentRowChanged.connect(self.select_rule)
        self.rule_list.itemChanged.connect(self.item_changed)
        ll.addWidget(self.rule_list, 1)
        commands = QHBoxLayout()
        commands.addWidget(action("+ ADD RULE", self.add_rule))
        commands.addWidget(action("REMOVE", self.remove_rule))
        ll.addLayout(commands)
        order = QHBoxLayout()
        order.addWidget(action("MOVE UP", lambda: self.move_rule(-1)))
        order.addWidget(action("MOVE DOWN", lambda: self.move_rule(1)))
        ll.addLayout(order)
        profiles = QHBoxLayout()
        profiles.addWidget(action("IMPORT PROFILE", self.import_profile))
        profiles.addWidget(action("EXPORT", self.export_profile))
        ll.addLayout(profiles)
        splitter.addWidget(left)
        right = QWidget()
        rr = QVBoxLayout(right)
        rr.setContentsMargins(14, 0, 0, 0)
        self.form_panel = QWidget()
        form = QFormLayout(self.form_panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(12)
        self.rule_name = QLineEdit()
        self.rule_name.setMaxLength(120)
        form.addRow("Rule name", self.rule_name)
        self.kind = QComboBox()
        for kind, (name, _) in TEMPLATES.items():
            self.kind.addItem(name, kind)
        form.addRow("Behaviour", self.kind)
        self.scope = QComboBox()
        self.scope.addItems(["all", "dialogue", "outside"])
        form.addRow("Apply within", self.scope)
        self.exceptions = QLineEdit()
        self.exceptions.setPlaceholderText("Skip lines containing these phrases, comma separated")
        form.addRow("Exceptions", self.exceptions)
        self.enabled = QCheckBox("Enabled for this project")
        form.addRow("", self.enabled)
        self.example = hint("")
        form.addRow("Example", self.example)
        self.custom_panel = QWidget()
        custom = QFormLayout(self.custom_panel)
        custom.setContentsMargins(0, 0, 0, 0)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Text to find")
        self.find.setMaxLength(2000)
        self.replacement = QLineEdit()
        self.replacement.setPlaceholderText("Replacement (may be empty)")
        self.replacement.setMaxLength(2000)
        self.whole_word = QCheckBox("Whole words only")
        self.case_sensitive = QCheckBox("Match letter case")
        custom.addRow("Find", self.find)
        custom.addRow("Replace", self.replacement)
        custom.addRow("", self.whole_word)
        custom.addRow("", self.case_sensitive)
        form.addRow(self.custom_panel)
        rr.addWidget(self.form_panel)
        self.error_label = QLabel()
        self.error_label.setObjectName("orange")
        self.error_label.setWordWrap(True)
        rr.addWidget(self.error_label)
        rr.addWidget(hint("LIVE SANDBOX · Try a sentence here"))
        self.sample = QPlainTextEdit()
        self.sample.setObjectName("notes")
        self.sample.setPlainText(
            sample
            or 'She said "Hello" she said.\n"A quote", followed by a comma.\nTwo   spaces between words.'
        )
        self.sample.setMinimumHeight(100)
        rr.addWidget(self.sample, 1)
        self.preview_label = hint("PREVIEW · Your transcript stays unchanged")
        rr.addWidget(self.preview_label)
        self.result = QPlainTextEdit()
        self.result.setObjectName("notes")
        self.result.setReadOnly(True)
        rr.addWidget(self.result, 1)
        splitter.addWidget(right)
        splitter.setSizes([330, 580])
        layout.addWidget(splitter, 1)
        self.review_on_export = QCheckBox("Review enabled rules before exporting a document")
        self.review_on_export.setChecked(review_on_export)
        layout.addWidget(self.review_on_export)
        footer = QHBoxLayout()
        footer.addWidget(hint("Use CHECK RULES in the workbench to review and apply changes."), 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh_preview)
        for widget in (self.rule_name, self.find, self.replacement):
            widget.textChanged.connect(self.form_changed)
        self.exceptions.textChanged.connect(self.form_changed)
        self.scope.currentIndexChanged.connect(self.form_changed)
        for widget in (self.enabled, self.whole_word, self.case_sensitive):
            widget.toggled.connect(self.form_changed)
        self.kind.currentIndexChanged.connect(self.form_changed)
        self.sample.textChanged.connect(self.timer.start)
        self.populate()
        self.refresh_preview()

    def populate(self, identity=None):
        self.loading = True
        self.rule_list.clear()
        for rule in self.rules:
            item = QListWidgetItem(rule.name)
            item.setData(Qt.UserRole, rule.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if rule.enabled else Qt.Unchecked)
            item.setToolTip(TEMPLATES[rule.kind][1])
            self.rule_list.addItem(item)
        self.loading = False
        index = next((i for i, r in enumerate(self.rules) if r.id == identity), 0)
        self.rule_list.setCurrentRow(index if self.rules else -1)
        if not self.rules:
            self.select_rule(-1)

    def selected_rule(self):
        return next((r for r in self.rules if r.id == self.selected_id), None)

    def select_rule(self, row):
        if self.loading:
            return
        self.loading = True
        rule = self.rules[row] if 0 <= row < len(self.rules) else None
        self.selected_id = rule.id if rule else None
        self.form_panel.setEnabled(rule is not None)
        if rule:
            self.rule_name.setText(rule.name)
            self.scope.setCurrentText(rule.scope)
            self.exceptions.setText(rule.exceptions)
            self.kind.setCurrentIndex(self.kind.findData(rule.kind))
            self.enabled.setChecked(rule.enabled)
            self.find.setText(rule.find)
            self.replacement.setText(rule.replacement)
            self.whole_word.setChecked(rule.whole_word)
            self.case_sensitive.setChecked(rule.case_sensitive)
            self.example.setText(TEMPLATES[rule.kind][1])
            self.custom_panel.setVisible(rule.kind == "replace")
        self.loading = False

    def form_changed(self, *_):
        if self.loading:
            return
        rule = self.selected_rule()
        if not rule:
            return
        rule.name = self.rule_name.text()
        rule.scope = self.scope.currentText()
        rule.exceptions = self.exceptions.text()
        rule.kind = self.kind.currentData()
        rule.enabled = self.enabled.isChecked()
        rule.find, rule.replacement = self.find.text(), self.replacement.text()
        rule.whole_word, rule.case_sensitive = (
            self.whole_word.isChecked(),
            self.case_sensitive.isChecked(),
        )
        self.example.setText(TEMPLATES[rule.kind][1])
        self.custom_panel.setVisible(rule.kind == "replace")
        self.loading = True
        item = self.rule_list.currentItem()
        if item:
            item.setText(rule.name or "Untitled rule")
            item.setCheckState(Qt.Checked if rule.enabled else Qt.Unchecked)
        self.loading = False
        self.timer.start()

    def item_changed(self, item):
        if self.loading:
            return
        rule = next(r for r in self.rules if r.id == item.data(Qt.UserRole))
        rule.enabled = item.checkState() == Qt.Checked
        if rule.id == self.selected_id:
            self.loading = True
            self.enabled.setChecked(rule.enabled)
            self.loading = False
        self.timer.start()

    def refresh_preview(self):
        try:
            validate_rules([r.to_dict() for r in self.rules])
            preview = preview_rules(self.sample.toPlainText(), self.rules)
            self.result.setPlainText(preview.after)
            # Highlight changed ranges in the result, accounting for prior length shifts.
            shift = 0
            spans = []
            for edit in preview.edits:
                spans.append((edit.start + shift, edit.start + shift + len(edit.replacement)))
                shift += len(edit.replacement) - (edit.end - edit.start)
            highlight_changes(self.result, spans)
            self.preview_label.setText(
                f"PREVIEW · {len(preview.edits)} change(s) · Transcript unchanged"
            )
            self.error_label.clear()
            self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        except (ValueError, TypeError) as error:
            self.error_label.setText(str(error))
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)

    def add_rule(self):
        names = [value[0] for value in TEMPLATES.values()]
        name, accepted = QInputDialog.getItem(
            self, "Add writing rule", "Choose a starting point:", names, 0, False
        )
        if accepted:
            kind = next(k for k, value in TEMPLATES.items() if value[0] == name)
            rule = new_rule(kind)
            self.rules.append(rule)
            self.populate(rule.id)
            self.timer.start()

    def remove_rule(self):
        if self.selected_id:
            self.rules = [r for r in self.rules if r.id != self.selected_id]
            self.populate()
            self.timer.start()

    def move_rule(self, delta):
        index = self.rule_list.currentRow()
        target = index + delta
        if 0 <= index < len(self.rules) and 0 <= target < len(self.rules):
            self.rules[index], self.rules[target] = self.rules[target], self.rules[index]
            self.populate(self.selected_id)
            self.timer.start()

    def save(self):
        self.refresh_preview()
        if self.buttons.button(QDialogButtonBox.Save).isEnabled():
            self.accept()

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import rule profile", "", "Rule profiles (*.json)"
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > 1_000_000:
                raise ValueError("This profile is too large.")
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != "transcriber-rules/1":
                raise ValueError("Not a Document Transcriber rule profile.")
            self.rules = validate_rules(payload.get("rules"))
            self.populate()
            self.refresh_preview()
        except (ValueError, TypeError, OSError) as error:
            QMessageBox.warning(self, "Could not import profile", str(error))

    def export_profile(self):
        try:
            validate_rules([r.to_dict() for r in self.rules])
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Fix this profile first", str(error))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export rule profile", "writing-rules.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        {
                            "format": "transcriber-rules/1",
                            "rules": [r.to_dict() for r in self.rules],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                QMessageBox.warning(self, "Could not export profile", str(error))


class RuleReviewDialog(QDialog):
    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.preview = preview
        self.declined = False
        self.setWindowTitle("Review writing-rule changes")
        self.resize(1020, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(f"{len(preview.edits)} PROPOSED CHANGES")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(
            hint(
                "Check the changes you want. Applying them is one undoable edit; your original scan is preserved."
            )
        )
        split = QSplitter(Qt.Horizontal)
        self.changes = QListWidget()
        self.changes.setMinimumWidth(220)
        for edit in preview.edits:
            original = preview.before[edit.start : edit.end]
            context = preview.before[max(0, edit.start - 18) : edit.start].replace("\n", "↵")
            item = QListWidgetItem(f"…{context}\n{original or '∅'}  →  {edit.replacement or '∅'}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.changes.addItem(item)
        self.changes.itemChanged.connect(self.refresh)
        split.addWidget(self.changes)
        text_panel = QWidget()
        tl = QVBoxLayout(text_panel)
        tl.setContentsMargins(12, 0, 0, 0)
        tl.addWidget(hint("AFTER · Selected changes highlighted"))
        self.after = QPlainTextEdit()
        self.after.setReadOnly(True)
        tl.addWidget(self.after, 1)
        split.addWidget(text_panel)
        split.setSizes([300, 680])
        layout.addWidget(split, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(hint("Rules: " + "; ".join(preview.applied_rules)), 1)
        bottom.addWidget(action("CANCEL", self.reject))
        bottom.addWidget(action("KEEP ORIGINAL", self.keep_original))
        self.apply_button = action("APPLY CHANGES", self.accept, True)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self.refresh()

    def selected_edits(self):
        if self.declined:
            return []
        return [
            edit
            for index, edit in enumerate(self.preview.edits)
            if self.changes.item(index).checkState() == Qt.Checked
        ]

    def keep_original(self):
        self.declined = True
        self.accept()

    def refresh(self, *_):
        edits = self.selected_edits()
        text = self.preview.before
        for edit in reversed(edits):
            text = text[: edit.start] + edit.replacement + text[edit.end :]
        self.after.setPlainText(text)
        shift, spans = 0, []
        for edit in edits:
            spans.append((edit.start + shift, edit.start + shift + len(edit.replacement)))
            shift += len(edit.replacement) - (edit.end - edit.start)
        highlight_changes(self.after, spans)
        self.apply_button.setText(f"APPLY {len(edits)} CHANGE(S)")
        self.apply_button.setEnabled(bool(edits))
