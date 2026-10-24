import json
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from .advanced_ui import (
    CornerDialog,
    HistoryDialog,
    LineDialog,
    PhraseDialog,
    PreferencesDialog,
    ProfileDialog,
    QueueDialog,
    ReadingDialog,
)
from .ocr import handwritten_ocr, printed_ocr
from .rules import Edit
from .theme import STYLE
from .workspace_tools import TERMINOLOGY, deskew, perspective, suppress_bleed


class AdvancedFeatures:
    def effective_rules(self):
        from .rules import WritingRule

        rules = self.store.writing_rules()
        profile = self.store.preference("writers", {}).get(
            self.store.preference("active_writer", "Default"), {}
        )
        return rules + [
            WritingRule("writer-" + str(i), "Expand " + a, "replace", True, a, b)
            for i, (a, b) in enumerate(profile.get("abbreviations", {}).items())
        ]

    def install_advanced(self):
        self.queue_paused = True
        self.active_queue_id = None
        self.edit_source = "manual"
        with self.store.db:
            self.store.db.execute("UPDATE queue SET status='queued' WHERE status='running'")
        menu = self.menuBar().addMenu("Workspace")
        for title, fn, key in [
            ("Line-by-line transcription…", self.line_mode, "Ctrl+L"),
            ("Compare two OCR engines…", self.compare_readings, "Ctrl+Shift+R"),
            ("Review split / merged words…", self.review_phrases, "Ctrl+Shift+P"),
            ("Writer profiles & terminology…", self.writer_profiles, None),
            ("Page fidelity: faithful / cleaned…", self.fidelity, None),
            ("Revision history…", self.history, "Ctrl+H"),
            ("Processing queue…", self.show_queue, None),
            ("Add selected region to reading order", self.add_reading_region, None),
            ("Edit reading order…", self.edit_reading_order, None),
            ("Recognize ordered regions", self.recognize_ordered, None),
            ("Deskew scan", lambda: self.scan_tool("deskew"), None),
            ("Reduce bleed-through", lambda: self.scan_tool("bleed"), None),
            ("Correct perspective…", lambda: self.scan_tool("perspective"), None),
            ("Export writer training examples…", self.export_training, None),
            ("Save selected region as writer example…", self.save_writer_example, None),
            ("Unload handwriting model", self.unload_model, None),
            ("Accessibility & shortcuts…", self.preferences, None),
        ]:
            self.add_action(menu, title, fn, key)
        # Avoid duplicating the existing batch shortcut.
        for action in self.tools_menu.actions():
            if action.text() == "Recognize blank pages in document":
                action.setShortcut("")
        self.advanced_menu = menu
        self._default_shortcuts = {
            a.text(): a.shortcut().toString()
            for a in self.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction)
        }
        for action in self.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction):
            custom = self.store.preference("shortcuts", {}).get(action.text())
            if custom is not None:
                action.setShortcut(QKeySequence(custom))
        font = self.editor.font()
        font.setPointSize(self.store.preference("editor_font", 12))
        self.editor.setFont(font)
        self.apply_accessibility()
        self.reload_dictionary()

    def ready_page(self):
        return not self.busy and self.current_page is not None

    def apply_accessibility(self):
        if hasattr(self, "_default_shortcuts"):
            custom = self.store.preference("shortcuts", {})
            for action in self.findChildren(
                __import__("PySide6.QtGui", fromlist=["QAction"]).QAction
            ):
                action.setShortcut(
                    QKeySequence(
                        custom.get(action.text(), self._default_shortcuts.get(action.text(), ""))
                    )
                )
        font = self.editor.font()
        font.setPointSize(self.store.preference("editor_font", 12))
        self.editor.setFont(font)
        high = self.store.preference("high_contrast", False)
        self.setStyleSheet(
            STYLE
            + (
                "\nQWidget {color:#ffffff;} QPlainTextEdit,QLineEdit {background:#000000;color:#ffffff;} QLabel#muted {color:#c7cdd1;}"
                if high
                else ""
            )
        )
        for widget in [self.editor, self.viewer, self.lookup, self.library]:
            widget.setAccessibleName(
                widget.accessibleName()
                or {
                    self.editor: "Transcription editor",
                    self.viewer: "Source document",
                    self.lookup: "Dictionary lookup",
                    self.library: "Document library",
                }[widget]
            )

    def line_mode(self):
        if not self.ready_page() or not self.save_current():
            return
        saved = self.store.preference("lines:" + self.current_page.id, {})
        if saved.get("text") != self.editor.toPlainText():
            saved.pop("lines", None)
        regions = self.store.preference("regions:" + self.current_page.id, [])
        if regions:
            saved = {**saved, "boxes": regions}
        dialog = LineDialog(self.store.page(self.current_page.id), saved, self)
        if dialog.exec() == QDialog.Accepted:
            self.store.set_preference(
                "lines:" + self.current_page.id,
                {"boxes": dialog.boxes, "lines": dialog.lines, "text": "\n".join(dialog.lines)},
            )
            self.replace_transcription("\n".join(dialog.lines), "manual: line mode")

    def replace_transcription(self, text, source):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.edit_source = source
        self.queue_save()

    def history(self):
        if not self.ready_page() or not self.save_current():
            return
        revisions = self.store.revisions(self.current_page.id)
        if not revisions:
            self.statusBar().showMessage("No text revisions yet.")
            return
        dialog = HistoryDialog(revisions, self.editor.toPlainText(), self)
        if dialog.exec() == QDialog.Accepted and dialog.list.currentRow() >= 0:
            self.replace_transcription(
                revisions[dialog.list.currentRow()]["text"], "restored revision"
            )

    def fidelity(self):
        if not self.ready_page() or not self.save_current():
            return
        key = "fidelity:" + self.current_page.id
        state = self.store.preference(
            key,
            {
                "mode": "faithful",
                "faithful": self.editor.toPlainText(),
                "cleaned": self.editor.toPlainText(),
            },
        )
        mode, ok = QInputDialog.getItem(
            self,
            "Page fidelity",
            "Faithful preserves the original wording; cleaned is a separate editable copy.",
            ["faithful", "cleaned"],
            0 if state["mode"] == "faithful" else 1,
            False,
        )
        if ok:
            state[state["mode"]] = self.editor.toPlainText()
            state["mode"] = mode
            self.store.set_preference(key, state)
            self.replace_transcription(state[mode], f"fidelity: {mode}")
            self.document_subtitle.setText(
                self.document_subtitle.text().split(" · Reading:")[0] + f" · Reading: {mode}"
            )
            self.save_current()

    def profile_words(self):
        profiles = self.store.preference("writers", {})
        profile = profiles.get(self.store.preference("active_writer", "Default"), {})
        return profile.get("words", []) + TERMINOLOGY.get(profile.get("pack", "General"), [])

    def profile_corrections(self):
        profile = self.store.preference("writers", {}).get(
            self.store.preference("active_writer", "Default"), {}
        )
        return {**self.store.corrections(), **profile.get("corrections", {})}

    def learn_writer_correction(self, original, replacement):
        name = self.store.preference("active_writer", "Default")
        if name == "Default":
            self.store.learn_correction(original, replacement)
            return
        profiles = self.store.preference("writers", {})
        profile = profiles.setdefault(name, {})
        profile.setdefault("corrections", {})[original.casefold()] = replacement
        self.store.set_preference("writers", profiles)

    def writer_profiles(self):
        if self.busy:
            return
        dialog = ProfileDialog(
            self.store.preference("writers", {}),
            self.store.preference("active_writer", "Default"),
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.store.set_preference("writers", dialog.profiles)
            self.store.set_preference("active_writer", dialog.names.currentText())
            self.reload_dictionary()
            self.statusBar().showMessage(
                "Writer vocabulary and abbreviations activated. Model weights are unchanged."
            )

    def review_phrases(self):
        if not self.ready_page():
            return
        dialog = PhraseDialog(self.editor.toPlainText(), self.dictionary, self)
        if dialog.exec() == QDialog.Accepted and dialog.list.currentRow() >= 0:
            p = dialog.proposals[dialog.list.currentRow()]
            self.apply_rule_edits(self.editor.toPlainText(), [Edit(p.start, p.end, p.replacement)])
            self.edit_source = "dictionary: phrase"

    def compare_readings(self):
        if not self.ready_page():
            return
        path = self.current_page.image_path
        region = self.viewer.region_tuple()

        def run(cancel, progress):
            return printed_ocr(path, region, cancel, progress), handwritten_ocr(
                path, region, self.model_dir, cancel, progress
            )

        def finish(results):
            dialog = ReadingDialog(*results, self)
            if dialog.exec() == QDialog.Accepted:
                result = dialog.choice
                if region:
                    self.editor.insertPlainText(result.text)
                else:
                    self.replace_transcription(result.text, "OCR comparison")
                    self.tokens = result.tokens
                    self.viewer.tokens = self.tokens
                self.engine_name = result.engine
                self.edit_source = "OCR comparison"

        self._run_job(run, finish)

    def add_reading_region(self):
        if not self.ready_page():
            return
        region = self.viewer.region_tuple()
        if not region:
            self.statusBar().showMessage("Select a region in the source first.")
            return
        key = "regions:" + self.current_page.id
        regions = self.store.preference(key, [])
        regions.append(region)
        self.store.set_preference(key, regions)
        self.viewer.ordered_regions = regions
        self.viewer.viewport().update()
        self.statusBar().showMessage(f"Region added at reading-order position {len(regions)}.")

    def edit_reading_order(self):
        if not self.ready_page():
            return
        key = "regions:" + self.current_page.id
        regions = self.store.preference(key, [])
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Reading order",
            "One x,y,width,height per line. Reorder rows or remove a row.",
            "\n".join(",".join(map(str, r)) for r in regions),
        )
        if ok:
            try:
                values = [
                    list(map(int, line.split(","))) for line in text.splitlines() if line.strip()
                ]
                with Image.open(self.current_page.image_path) as image:
                    w, h = image.size
                if any(
                    len(r) != 4
                    or min(r) < 0
                    or r[2] < 1
                    or r[3] < 1
                    or r[0] + r[2] > w
                    or r[1] + r[3] > h
                    for r in values
                ):
                    raise ValueError("Regions must lie inside the scan.")
                self.store.set_preference(key, values)
                self.viewer.ordered_regions = values
                self.viewer.viewport().update()
            except ValueError as error:
                self.error("Invalid reading order", error)

    def recognize_ordered(self):
        if not self.ready_page():
            return
        regions = self.store.preference("regions:" + self.current_page.id, [])
        if not regions:
            self.statusBar().showMessage("Add regions in reading order first.")
            return
        if (
            self.editor.toPlainText()
            and QMessageBox.question(
                self, "Replace text?", "Replace this page with the ordered-region OCR result?"
            )
            != QMessageBox.Yes
        ):
            return
        path = self.current_page.image_path
        hand = self.engine.currentIndex() == 1

        def run(cancel, progress):
            results = []
            for region in regions:
                results.append(
                    handwritten_ocr(path, region, self.model_dir, cancel, progress)
                    if hand
                    else printed_ocr(path, region, cancel, progress)
                )
            return results

        self._run_job(
            run,
            lambda results: self.replace_transcription(
                "\n".join(r.text for r in results), "OCR: ordered regions"
            ),
        )

    def scan_tool(self, kind):
        if not self.ready_page() or not self.save_current():
            return
        points = None
        if kind == "perspective":
            dialog = CornerDialog(self.current_page.image_path, self)
            if dialog.exec() != QDialog.Accepted:
                return
            points = dialog.points
        page_id = self.current_page.id
        path = self.current_page.image_path

        def run(cancel, progress):
            with Image.open(path) as source:
                image = source.convert("RGB")
            if kind == "deskew":
                image, _ = deskew(image)
            elif kind == "bleed":
                image = suppress_bleed(image)
            else:
                image = perspective(image, points)
            return image

        def finish(image):
            target = self.store.root / "images" / f"{page_id}-{uuid4().hex[:8]}.png"
            image.save(target)
            self.tokens = []
            self.store.set_image(page_id, target)
            self.store.set_preference("regions:" + page_id, [])
            self.store.set_preference("lines:" + page_id, {})
            self.load_page(page_id, save=False)

        self._run_job(run, finish)

    def save_writer_example(self):
        if not self.ready_page():
            return
        region = self.viewer.region_tuple()
        if not region:
            self.statusBar().showMessage("Select one handwritten line first.")
            return
        text, ok = QInputDialog.getText(
            self, "Writer training example", "Verified transcription for this line:"
        )
        if ok and text.strip():
            writer = self.store.preference("active_writer", "Default")
            key = "writer_examples"
            items = self.store.preference(key, [])
            target = self.store.root / "images" / f"writer-{uuid4().hex}.png"
            x, y, w, h = region
            with Image.open(self.current_page.image_path) as image:
                image.crop((x, y, x + w, y + h)).save(target)
            items.append(
                {"writer": writer, "image": str(target.relative_to(self.store.root)), "text": text}
            )
            self.store.set_preference(key, items)

    def export_training(self):
        if self.busy:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose an empty training export folder")
        if not folder:
            return
        import shutil

        root = Path(folder)
        if any(root.iterdir()):
            self.error("Choose an empty folder", "Training exports need an empty folder.")
            return
        items = self.store.preference("writer_examples", [])
        for item in items:
            shutil.copyfile(self.store.root / item["image"], root / Path(item["image"]).name)
        (root / "metadata.jsonl").write_text(
            "\n".join(json.dumps({**item, "image": Path(item["image"]).name}) for item in items),
            encoding="utf-8",
        )
        (root / "README.txt").write_text(
            "Verified writer samples for an external fine-tuning workflow. No model has been trained by this export.\n"
        )

    def unload_model(self):
        if self.busy:
            return
        from . import ocr

        ocr._loaded_model = None
        ocr._loaded_path = None
        import gc

        gc.collect()
        self.statusBar().showMessage("Handwriting model unloaded from memory.")

    def preferences(self):
        if not self.busy:
            PreferencesDialog(self).exec()

    def show_queue(self):
        QueueDialog(self).exec()

    def queue_document(self):
        if not self.current_page:
            return
        if self.busy:
            return
        if not self.save_current():
            return
        self.store.enqueue(
            [p.id for p in self.store.pages(self.current_page.document_id) if not p.text.strip()],
            "handwriting" if self.engine.currentIndex() == 1 else "printed",
        )

    def start_queue(self):
        self.queue_paused = False
        self.queue_next()

    def pause_queue(self):
        self.queue_paused = True

    def queue_next(self):
        if self.queue_paused or self.busy or self._closed:
            return
        jobs = [j for j in self.store.queue_items() if j["status"] == "queued"]
        if not jobs:
            return
        job = jobs[0]
        page = self.store.page(job["page_id"])
        if page.text.strip():
            self.store.queue_update(job["id"], "skipped", "Existing transcription preserved")
            QTimer.singleShot(0, self.queue_next)
            return
        self.active_queue_id = job["id"]
        self.store.queue_update(job["id"], "running")

        def run(cancel, progress):
            return (
                handwritten_ocr(page.image_path, None, self.model_dir, cancel, progress)
                if job["engine"] == "handwriting"
                else printed_ocr(page.image_path, None, cancel, progress)
            )

        def finish(result):
            if not result.text:
                raise ValueError("No text detected")
            self.store.save_page(
                page.id, result.text, result.tokens, page.notes, False, result.engine, "OCR: queue"
            )
            self.store.queue_update(job["id"], "done")
            self.active_queue_id = None
            if self.current_page and self.current_page.id == page.id:
                self.load_page(page.id, save=False)
            self.refresh_library()
            QTimer.singleShot(0, self.queue_next)

        self._run_job(run, finish)

    def queue_result(self, error, cancelled):
        if self.active_queue_id is not None:
            self.store.queue_update(
                self.active_queue_id,
                "queued" if cancelled else "failed",
                error or ("Cancelled" if cancelled else "Could not apply result"),
            )
            self.active_queue_id = None
            self.queue_paused = True
