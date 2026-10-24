"""Focused tools: lines, history, writer profiles, queues, and preferences."""

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .ocr import line_regions
from .workspace_tools import TERMINOLOGY, comparison, phrase_suggestions


class CornerDialog(QDialog):
    def __init__(self, path, parent=None):
        from PySide6.QtGui import QColor, QPen
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

        super().__init__(parent)
        self.setWindowTitle("Perspective correction")
        self.resize(900, 700)
        self.points = []
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Click TOP LEFT, TOP RIGHT, BOTTOM RIGHT, BOTTOM LEFT of the document.")
        )
        scene = QGraphicsScene(self)
        view = QGraphicsView(scene)
        scene.addPixmap(QPixmap(str(path)))
        layout.addWidget(view, 1)
        self.markers = []

        def press(event):
            if len(self.points) >= 4:
                return
            point = view.mapToScene(event.position().toPoint())
            if not scene.sceneRect().contains(point):
                return
            self.points.append((point.x(), point.y()))
            self.markers.append(
                scene.addEllipse(
                    point.x() - 5, point.y() - 5, 10, 10, QPen(QColor("#ff9147")), QColor("#ff9147")
                )
            )

        view.mousePressEvent = press

        def reset():
            self.points.clear()
            for marker in self.markers:
                scene.removeItem(marker)
            self.markers.clear()

        layout.addWidget(btn("RESET CORNERS", reset))
        layout.addWidget(btn("APPLY", lambda: self.accept() if len(self.points) == 4 else None))
        layout.addWidget(btn("CANCEL", self.reject))
        QTimer.singleShot(0, lambda: view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio))


def btn(text, callback):
    b = QPushButton(text)
    b.clicked.connect(callback)
    return b


class LineDialog(QDialog):
    def __init__(self, page, saved, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Line-by-line transcription")
        self.resize(1000, 600)
        self.image = Image.open(page.image_path).convert("RGB")
        self.boxes = saved.get("boxes") or line_regions(self.image)
        if not self.boxes:
            self.boxes = [(0, 0, *self.image.size)]
        self.lines = saved.get("lines", [])
        if len(self.lines) != len(self.boxes):
            initial = page.text.splitlines()
            self.lines = [initial[i] if i < len(initial) else "" for i in range(len(self.boxes))]
        self.index = 0
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        layout.addWidget(self.heading)
        self.scan = QLabel()
        self.scan.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.scan)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 2)
        self.text = QPlainTextEdit()
        self.text.setAccessibleName("Transcription for the current handwritten line")
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        previous = btn("PREVIOUS · Alt+Left", lambda: self.move(-1))
        previous.setShortcut("Alt+Left")
        row.addWidget(previous)
        nxt = btn("NEXT · Alt+Right", lambda: self.move(1))
        nxt.setShortcut("Alt+Right")
        row.addWidget(nxt)
        layout.addLayout(row)
        layout.addWidget(
            QLabel(
                "Segmentation is approximate. Configure ordered regions in the source viewer for complex pages."
            )
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.finish)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.show_line()

    def show_line(self):
        x, y, w, h = self.boxes[self.index]
        crop = self.image.crop((x, y, x + w, y + h))
        pix = QPixmap.fromImage(ImageQt(crop))
        self.scan.setPixmap(pix.scaled(940, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.heading.setText(f"LINE {self.index + 1} / {len(self.boxes)}")
        self.text.setPlainText(self.lines[self.index])
        self.text.setFocus()

    def move(self, delta):
        self.lines[self.index] = self.text.toPlainText()
        self.index = max(0, min(len(self.boxes) - 1, self.index + delta))
        self.show_line()

    def finish(self):
        self.lines[self.index] = self.text.toPlainText()
        self.accept()


class HistoryDialog(QDialog):
    def __init__(self, revisions, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Revision history")
        self.resize(950, 650)
        self.revisions = revisions
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        for r in revisions:
            self.list.addItem(f"#{r['id']} · {r['created']} · {r['source']}")
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.before = QPlainTextEdit()
        self.before.setReadOnly(True)
        self.after = QPlainTextEdit()
        self.after.setReadOnly(True)
        self.after.setPlainText(current)
        row.addWidget(self.before)
        row.addWidget(self.after)
        layout.addLayout(row, 1)
        self.diff = QLabel()
        self.diff.setWordWrap(True)
        layout.addWidget(self.diff)
        self.list.currentRowChanged.connect(lambda i: self.select(i, current))
        layout.addWidget(btn("RESTORE SELECTED VERSION", self.accept))
        layout.addWidget(btn("CLOSE", self.reject))
        self.list.setCurrentRow(0)

    def select(self, index, current):
        if index >= 0:
            text = self.revisions[index]["text"]
            self.before.setPlainText(text)
            self.diff.setText(
                "\n".join(f"{a or '∅'} → {b or '∅'}" for _, a, b in comparison(text, current))[
                    :3000
                ]
                or "No text differences."
            )


class ProfileDialog(QDialog):
    def __init__(self, profiles, active, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Writer profiles & terminology")
        self.resize(700, 650)
        self.profiles = dict(profiles)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.names = QComboBox()
        self.names.addItems(self.profiles or ["Default"])
        self.names.setCurrentText(active)
        form.addRow("Writer", self.names)
        self.pack = QComboBox()
        self.pack.addItems(TERMINOLOGY)
        form.addRow("Terminology", self.pack)
        self.words = QPlainTextEdit()
        self.words.setPlaceholderText("Names and specialist words, one per line")
        form.addRow("Vocabulary", self.words)
        self.abbreviations = QPlainTextEdit()
        self.abbreviations.setPlaceholderText("abbr = expanded phrase, one per line")
        form.addRow("Abbreviations", self.abbreviations)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Letter-shape observations, e.g. this writer’s r resembles v")
        form.addRow("Writer notes", self.notes)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(
                "Profiles store vocabulary, abbreviations, and observations. They do not retrain the handwriting model."
            )
        )
        layout.addWidget(btn("NEW WRITER", self.add))
        layout.addWidget(btn("SAVE PROFILE & ACTIVATE", self.finish))
        layout.addWidget(btn("CANCEL", self.reject))
        self.names.currentTextChanged.connect(self.load)
        self.load(self.names.currentText())

    def load(self, name):
        profile = self.profiles.get(name, {})
        self.pack.setCurrentText(profile.get("pack", "General"))
        self.words.setPlainText("\n".join(profile.get("words", [])))
        self.abbreviations.setPlainText(
            "\n".join(f"{k} = {v}" for k, v in profile.get("abbreviations", {}).items())
        )
        self.notes.setPlainText(profile.get("notes", ""))

    def add(self):
        name, ok = QInputDialog.getText(self, "New writer", "Name:")
        if ok and name.strip() and name not in self.profiles:
            self.profiles[name] = {}
            self.names.addItem(name)
            self.names.setCurrentText(name)

    def finish(self):
        pairs = {}
        for line in self.abbreviations.toPlainText().splitlines():
            if line.strip():
                if "=" not in line:
                    QMessageBox.warning(
                        self, "Invalid abbreviation", "Use abbreviation = expansion."
                    )
                    return
                a, b = line.split("=", 1)
                if not a.strip():
                    return
                pairs[a.strip()] = b.strip()
        self.profiles[self.names.currentText()] = {
            **self.profiles.get(self.names.currentText(), {}),
            "pack": self.pack.currentText(),
            "words": [w.strip() for w in self.words.toPlainText().splitlines() if w.strip()],
            "abbreviations": pairs,
            "notes": self.notes.toPlainText(),
        }
        self.accept()


class QueueDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Persistent processing queue")
        self.resize(800, 500)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in [
            ("ADD BLANK PAGES", window.queue_document),
            ("START / RESUME", window.start_queue),
            ("PAUSE", window.pause_queue),
            ("RETRY FAILED", self.retry),
            ("PRIORITIZE", self.prioritize),
        ]:
            row.addWidget(btn(text, fn))
        layout.addLayout(row)
        layout.addWidget(
            QLabel(
                "Pause stops after the current page. Completed pages persist across restarts. Existing text is preserved."
            )
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def refresh(self):
        current = self.list.currentRow()
        self.items = self.window.store.queue_items()
        self.list.clear()
        for item in self.items:
            self.list.addItem(
                f"{item['status'].upper()} · {item['title']} / {item['number']} · priority {item['priority']} · {item['error']}"
            )
        if current >= 0:
            self.list.setCurrentRow(current)

    def retry(self):
        for item in self.items:
            if item["status"] == "failed":
                self.window.store.queue_update(item["id"], "queued")
        self.refresh()

    def prioritize(self):
        index = self.list.currentRow()
        if index >= 0:
            with self.window.store.db:
                self.window.store.db.execute(
                    "UPDATE queue SET priority=priority+1 WHERE id=?", (self.items[index]["id"],)
                )
        self.refresh()


class ReadingDialog(QDialog):
    def __init__(self, left, right, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare OCR readings")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Different engines can both be wrong. Review disagreements against the original scan."
            )
        )
        if parent and parent.current_page:
            from .widgets import ImageViewer

            self.original = ImageViewer()
            self.original.load(parent.current_page.image_path)
            self.original.setMinimumHeight(160)
            region = parent.viewer.region
            if region:
                self.original._fit = False
                self.original.fitInView(region, Qt.KeepAspectRatio)
                QTimer.singleShot(0, lambda: self.original.fitInView(region, Qt.KeepAspectRatio))
            layout.addWidget(self.original, 1)
        row = QHBoxLayout()
        editors = []
        for name, result in [("Tesseract", left), ("TrOCR", right)]:
            col = QVBoxLayout()
            col.addWidget(QLabel(name))
            edit = QPlainTextEdit(result.text)
            edit.setReadOnly(True)
            editors.append(edit)
            col.addWidget(edit)
            row.addLayout(col)
        layout.addLayout(row, 1)
        from difflib import SequenceMatcher

        from .rule_ui import highlight_changes

        changes = [
            op
            for op in SequenceMatcher(None, left.text, right.text).get_opcodes()
            if op[0] != "equal"
        ]
        highlight_changes(editors[0], [(i, j) for _, i, j, _, _ in changes])
        highlight_changes(editors[1], [(i, j) for _, _, _, i, j in changes])
        diff = QPlainTextEdit(
            "\n".join(f"{a or '∅'} ⇄ {b or '∅'}" for _, a, b in comparison(left.text, right.text))
        )
        diff.setReadOnly(True)
        layout.addWidget(diff)
        self.choice = None
        bottom = QHBoxLayout()
        for name, result in [("USE TESSERACT", left), ("USE TROCR", right)]:
            bottom.addWidget(btn(name, lambda checked=False, r=result: self.choose(r)))
        bottom.addWidget(btn("KEEP EXISTING", self.reject))
        layout.addLayout(bottom)

    def choose(self, result):
        self.choice = result
        self.accept()


class PhraseDialog(QDialog):
    def __init__(self, text, dictionary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Split / merged-word review")
        self.resize(700, 500)
        self.proposals = phrase_suggestions(text, dictionary)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        for p in self.proposals:
            self.list.addItem(f"{p.original} → {p.replacement} · {p.reason}")
        layout.addWidget(self.list)
        layout.addWidget(
            QLabel(
                "Select one proposal. Review again after each change; no phrases are replaced automatically."
            )
        )
        layout.addWidget(btn("APPLY SELECTED", self.accept))
        layout.addWidget(btn("CLOSE", self.reject))
        self.list.setCurrentRow(0)


class PreferencesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Accessibility & shortcuts")
        self.resize(700, 600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.high = QCheckBox("High contrast surfaces")
        self.high.setChecked(window.store.preference("high_contrast", False))
        form.addRow(self.high)
        self.font = QComboBox()
        self.font.addItems(["12", "14", "16", "18", "22"])
        self.font.setCurrentText(str(window.editor.font().pointSize()))
        form.addRow("Editor font size", self.font)
        self.shortcuts = {}
        for action in window.findChildren(
            __import__("PySide6.QtGui", fromlist=["QAction"]).QAction
        ):
            if not action.text() or not action.shortcut().toString():
                continue
            edit = QLineEdit(action.shortcut().toString())
            form.addRow(action.text(), edit)
            self.shortcuts[action] = edit
        body = QWidget()
        body.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.window = window
        layout.addWidget(btn("SAVE", self.finish))
        layout.addWidget(btn("CANCEL", self.reject))

    def finish(self):
        values = [
            QKeySequence(edit.text()).toString(QKeySequence.PortableText)
            for edit in self.shortcuts.values()
            if edit.text().strip()
        ]
        if any(not value for value in values):
            QMessageBox.warning(
                self,
                "Invalid shortcut",
                "Use a valid key sequence, or leave the field empty to unassign it.",
            )
            return
        if len(values) != len(set(values)):
            QMessageBox.warning(self, "Shortcut conflict", "Each shortcut must be unique.")
            return
        for action, edit in self.shortcuts.items():
            action.setShortcut(QKeySequence(edit.text()))
        self.window.store.set_preference(
            "shortcuts", {a.text(): e.text() for a, e in self.shortcuts.items()}
        )
        self.window.store.set_preference("high_contrast", self.high.isChecked())
        font = self.window.editor.font()
        font.setPointSize(int(self.font.currentText()))
        self.window.editor.setFont(font)
        self.window.store.set_preference("editor_font", int(self.font.currentText()))
        self.window.apply_accessibility()
        self.accept()
