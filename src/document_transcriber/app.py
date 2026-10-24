from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageFilter, ImageOps
from PySide6.QtCore import QLockFile, QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .advanced_features import AdvancedFeatures
from .dictionary import WORD_RE, Dictionary, estimate, shift_tokens
from .documents import export_document, import_files, make_sample
from .model_ui import ModelLibraryDialog
from .models import MODEL_NAME, export_pack, install_pack
from .ocr import download_handwriting_model, handwritten_ocr, printed_ocr
from .rule_ui import RuleReviewDialog, RulesDialog
from .rules import preview_rules
from .storage import ProjectStore
from .theme import STYLE
from .widgets import ImageViewer, Job, SpellingHighlighter, TranscriptionEditor


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(name)
    return widget


def button(text, callback=None, kind="", tooltip=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if kind:
        widget.setObjectName(kind)
    if callback:
        widget.clicked.connect(callback)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def frame(name, orientation="vertical", margins=(14, 14, 14, 14), spacing=10):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QHBoxLayout(widget) if orientation == "horizontal" else QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return widget, layout


def py_to_qt(text: str, offset: int) -> int:
    return len(text[:offset].encode("utf-16-le")) // 2


def qt_to_py(text: str, offset: int) -> int:
    return len(text.encode("utf-16-le")[: offset * 2].decode("utf-16-le", errors="ignore"))


class MainWindow(AdvancedFeatures, QMainWindow):
    def __init__(
        self, data_dir: Path, project_dir: Path | None = None, model_dir: Path | None = None
    ):
        super().__init__()
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.data_dir / "settings.ini"), QSettings.IniFormat)
        self.model_dir = (
            Path(model_dir).resolve() if model_dir else self.data_dir / "models" / MODEL_NAME
        )
        self.store = None
        self.project_lock = None
        self.current_page = None
        self.tokens = []
        self.engine_name = ""
        self.previous_text = ""
        self.loading = False
        self._closed = False
        self.busy = False
        self.job = None
        self.job_success = None
        self.job_cleanup = None
        self.started = time.monotonic()
        self.review_wpm = int(self.settings.value("review_wpm", 40))
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(1)
        self._open_store(project_dir or self.data_dir / "workspace")
        self.dictionary = Dictionary(
            self.store.vocabulary() + self.profile_words(),
            self.profile_corrections(),
            self.store.reviewed_texts(),
        )
        self.setWindowTitle("Document Transcriber — Local Workbench")
        self.resize(1540, 960)
        self.setMinimumSize(1040, 680)
        self.setFont(QFont("DejaVu Sans", 9))
        self.setStyleSheet(STYLE)
        self._build_ui()
        self._build_menus()
        self.install_advanced()
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(600)
        self.autosave.timeout.connect(self.save_current)
        self.inspection_timer = QTimer(self)
        self.inspection_timer.setSingleShot(True)
        self.inspection_timer.setInterval(350)
        self.inspection_timer.timeout.connect(self.refresh_review)
        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self.update_metrics)
        self.session_timer.start(10000)
        self.refresh_library()
        self.set_page_enabled(False)
        self.refresh_vocabulary()
        self.statusBar().showMessage("Ready · Import a document or open the printed sample.")

    def _open_store(self, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root / ".project.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise RuntimeError("This project is already open in another application instance.")
        try:
            store = ProjectStore(root)
        except Exception:
            lock.unlock()
            raise
        if self.store:
            self.store.close()
            self.project_lock.unlock()
        self.store = store
        self.project_lock = lock

    def _build_ui(self):
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(container)

        top, row = frame("topbar", "horizontal", (22, 14, 18, 14), 14)
        mark = label("▥", "orange")
        mark.setStyleSheet("background:#f28b42;color:#17120e;font-size:28px;padding:1px 9px;")
        row.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(3)
        brand.addWidget(label("TRANSCRIBE", "brand"))
        brand.addWidget(label("DOCUMENT WORKBENCH", "eyebrow"))
        row.addLayout(brand)
        row.addStretch()
        row.addWidget(label("●  LOCAL PROCESSING", "orange"))
        row.addWidget(button("MODELS", self.show_models, "flat"))
        row.addSpacing(15)
        self.project_label = label(self.store.root.name.upper(), "badge")
        self.project_label.setToolTip(str(self.store.root))
        row.addWidget(self.project_label)
        row.addSpacing(5)
        row.addWidget(button("SHORTCUTS  ↗", self.show_shortcuts, "flat"))
        outer.addWidget(top)

        main = QSplitter(Qt.Horizontal)
        main.setChildrenCollapsible(False)
        outer.addWidget(main, 1)
        sidebar, side = frame("sidebar", margins=(14, 20, 14, 14), spacing=14)
        sidebar.setMinimumWidth(195)
        sidebar.setMaximumWidth(310)
        heading = QHBoxLayout()
        heading.addWidget(label("YOUR DOCUMENTS", "section"))
        heading.addStretch()
        self.import_plus = button("+", self.import_dialog, "flat", "Import documents · Ctrl+O")
        self.import_plus.setFixedSize(27, 27)
        self.import_plus.setStyleSheet("padding:0px;font-size:20px;")
        heading.addWidget(self.import_plus)
        side.addLayout(heading)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Search title or text…")
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(lambda: self.refresh_library())
        side.addWidget(self.library_search)
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.setIndentation(14)
        self.library.setWordWrap(True)
        self.library.itemSelectionChanged.connect(self.library_selected)
        side.addWidget(self.library, 1)
        self.library_count = label("0 DOCUMENTS", "section")
        side.addWidget(self.library_count)
        side.addWidget(button("+  IMPORT DOCUMENTS", self.import_dialog, "primary"))
        side.addWidget(button("OPEN PRINTED SAMPLE", self.open_sample, "flat"))
        rule, _ = frame("rule", margins=(0, 0, 0, 0))
        side.addWidget(rule)
        side.addWidget(label("PRIVATE BY DESIGN", "section"))
        privacy = label("Images, text, and your dictionary\nstay in this project on your device.")
        privacy.setWordWrap(True)
        side.addWidget(privacy)
        main.addWidget(sidebar)

        workspace, work = frame("workspace", margins=(0, 0, 0, 0), spacing=0)
        header, header_row = frame("toolbar", "horizontal", (20, 16, 20, 16))
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.document_title = label("Make every word readable.", "title")
        self.document_subtitle = label("Import a scan. Recognize the text. Make it yours.")
        titles.addWidget(self.document_title)
        titles.addWidget(self.document_subtitle)
        header_row.addLayout(titles, 1)
        self.export_button = button("EXPORT  ↗", self.export_current)
        header_row.addWidget(self.export_button)
        work.addWidget(header)

        recognition, controls = frame("toolbar", "horizontal", (16, 10, 16, 10), 8)
        controls.addWidget(label("ENGINE", "section"))
        self.engine = QComboBox()
        self.engine.addItems(["Printed · Tesseract", "Handwriting · TrOCR"])
        self.engine.setToolTip(
            "TrOCR is a dedicated handwriting model. Download it from Tools first."
        )
        controls.addWidget(self.engine)
        self.recognize_button = button(
            "RECOGNIZE TEXT",
            self.recognize,
            "primary",
            "Recognize this page or selected region · Ctrl+R",
        )
        controls.addWidget(self.recognize_button)
        self.region_label = label("FULL PAGE", "badge")
        controls.addWidget(self.region_label)
        controls.addStretch()
        self.rules_button = button(
            "RULES & STYLE",
            self.configure_rules,
            tooltip="Set project-specific quotation, spacing, and replacement rules",
        )
        self.rules_button.setText(
            f"RULES & STYLE · {sum(rule.enabled for rule in self.store.writing_rules())}"
        )
        controls.addWidget(self.rules_button)
        self.cancel_button = button("CANCEL", self.cancel_job, "flat")
        self.cancel_button.hide()
        controls.addWidget(self.cancel_button)
        work.addWidget(recognition)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        work.addWidget(self.progress)

        self.document_splitter = QSplitter(Qt.Horizontal)
        self.document_splitter.setChildrenCollapsible(False)
        viewer_panel, viewer_layout = frame("viewer", margins=(0, 0, 0, 0), spacing=0)
        viewer_header, viewer_row = frame("panelHeader", "horizontal", (14, 12, 10, 12), 5)
        viewer_row.addWidget(label("01  /  SOURCE", "section"), 1)
        self.zoom_label = label("FIT", "muted")
        viewer_row.addWidget(self.zoom_label)
        viewer_row.addWidget(button("−", lambda: self.viewer.zoom(1 / 1.2), "flat", "Zoom out"))
        viewer_row.addWidget(button("+", lambda: self.viewer.zoom(1.2), "flat", "Zoom in"))
        viewer_row.addWidget(
            button("FIT", lambda: self.viewer.fit_page(), "flat", "Fit page · Ctrl+0")
        )
        viewer_layout.addWidget(viewer_header)
        scan_tools, scan_row = frame("toolbar", "horizontal", (10, 7, 10, 7), 5)
        self.region_button = button(
            "SELECT REGION",
            kind="flat",
            tooltip="Drag a rectangle around one line, then run OCR. Region text is inserted at the editor cursor.",
        )
        self.region_button.setCheckable(True)
        self.region_button.toggled.connect(lambda checked: self.viewer.select_mode(checked))
        scan_row.addWidget(self.region_button)
        scan_row.addWidget(button("CLEAR", lambda: self.viewer.clear_region(), "flat"))
        scan_row.addStretch()
        self.rotate_button = button(
            "↻", lambda: self.process_image("rotate"), "flat", "Rotate scan 90° clockwise"
        )
        scan_row.addWidget(self.rotate_button)
        self.clean_button = button(
            "CLEAN",
            lambda: self.process_image("clean"),
            "flat",
            "Increase contrast and reduce scan noise",
        )
        scan_row.addWidget(self.clean_button)
        viewer_layout.addWidget(scan_tools)
        self.viewer = ImageViewer()
        self.viewer.regionChanged.connect(self.region_changed)
        self.viewer.wordClicked.connect(self.select_token)
        self.viewer.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        viewer_layout.addWidget(self.viewer, 1)
        viewer_footer, vf = frame("footer", "horizontal", (14, 10, 14, 10))
        self.page_label = label("NO PAGE SELECTED", "section")
        vf.addWidget(self.page_label, 1)
        vf.addWidget(label("CTRL + SCROLL  /  ZOOM"))
        viewer_layout.addWidget(viewer_footer)
        self.document_splitter.addWidget(viewer_panel)

        editor_panel, edit = frame("editorPanel", margins=(0, 0, 0, 0), spacing=0)
        editor_header, er = frame("panelHeader", "horizontal", (14, 16, 14, 16))
        er.addWidget(label("02  /  TRANSCRIPTION", "section"), 1)
        self.reviewed = QCheckBox("Reviewed")
        self.reviewed.toggled.connect(self.review_toggled)
        er.addWidget(self.reviewed)
        edit.addWidget(editor_header)
        editor_tools, et = frame("toolbar", "horizontal", (10, 7, 10, 7), 5)
        et.addWidget(button("UNDO", lambda: self.editor.undo(), "flat", "Ctrl+Z"))
        et.addWidget(button("REDO", lambda: self.editor.redo(), "flat", "Ctrl+Shift+Z"))
        et.addWidget(button("FIND", self.show_find, "flat", "Ctrl+F"))
        self.check_rules_button = button(
            "CHECK RULES",
            self.check_rules,
            "flat",
            "Preview and approve your writing-rule changes · Ctrl+Shift+K",
        )
        et.addWidget(self.check_rules_button)
        et.addStretch()
        et.addWidget(
            button(
                "COPY", lambda: QApplication.clipboard().setText(self.editor.toPlainText()), "flat"
            )
        )
        edit.addWidget(editor_tools)
        self.search_bar, search_layout = frame("toolbar", margins=(10, 8, 10, 8), spacing=6)
        search_top = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in this page")
        self.find_input.returnPressed.connect(self.find_next)
        search_top.addWidget(self.find_input)
        search_top.addWidget(button("NEXT", self.find_next, "flat"))
        search_top.addWidget(button("×", self.search_bar.hide, "flat"))
        search_layout.addLayout(search_top)
        search_bottom = QHBoxLayout()
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with")
        search_bottom.addWidget(self.replace_input)
        search_bottom.addWidget(button("ALL", self.replace_all))
        search_layout.addLayout(search_bottom)
        self.search_bar.hide()
        edit.addWidget(self.search_bar)
        self.editor = TranscriptionEditor()
        self.editor.dictionary = self.dictionary
        self.editor.textChanged.connect(self.text_changed)
        self.editor.cursorPositionChanged.connect(self.cursor_changed)
        self.editor.corrected.connect(
            lambda a, b: self.statusBar().showMessage(f"Learned correction: {a} → {b}", 4000)
        )
        self.highlighter = SpellingHighlighter(self.editor.document(), self.dictionary)
        edit.addWidget(self.editor, 1)
        edit_footer, ef = frame("footer", "horizontal", (14, 10, 14, 10))
        self.word_count = label("0 WORDS", "section")
        ef.addWidget(self.word_count, 1)
        self.save_status = label("LOCAL AUTOSAVE", "orange")
        ef.addWidget(self.save_status)
        edit.addWidget(edit_footer)
        self.document_splitter.addWidget(editor_panel)
        self.document_splitter.setSizes([520, 520])
        work.addWidget(self.document_splitter, 1)
        main.addWidget(workspace)

        self.inspector, inspect = frame("inspector", margins=(0, 0, 0, 0), spacing=0)
        self.inspector.setMinimumWidth(260)
        self.inspector.setMaximumWidth(390)
        inspector_header, ir = frame("panelHeader", margins=(16, 20, 16, 20))
        ir.addWidget(label("03  /  ASSISTANCE", "section"))
        inspect.addWidget(inspector_header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        inspect.addWidget(self.tabs, 1)
        dictionary_panel, dl = frame("dictionary", margins=(14, 18, 14, 14), spacing=12)
        dl.addWidget(label("DICTIONARY", "section"))
        description = label("Select a word in your text,\nor look one up below.")
        description.setWordWrap(True)
        dl.addWidget(description)
        self.lookup = QLineEdit()
        self.lookup.setPlaceholderText("Check a word…")
        self.lookup.returnPressed.connect(self.lookup_word)
        dl.addWidget(self.lookup)
        self.lookup_status = label("ENGLISH  /  OFFLINE", "orange")
        dl.addWidget(self.lookup_status)
        self.context_enabled = QCheckBox("Rank with sentence context")
        self.context_enabled.setChecked(self.store.preference("context_enabled", True))
        self.context_enabled.setToolTip(
            "Uses the bundled English model and pages you marked reviewed. No text leaves your device."
        )
        self.context_enabled.toggled.connect(self.context_changed)
        dl.addWidget(self.context_enabled)
        self.context_hint = label(
            "Select a word to use its sentence.\nStandalone lookup uses spelling similarity."
        )
        self.context_hint.setWordWrap(True)
        dl.addWidget(self.context_hint)
        dl.addWidget(label("SIMILAR WORDS · RANKED", "section"))
        self.suggestions = QListWidget()
        self.suggestions.setMinimumHeight(125)
        self.suggestions.itemDoubleClicked.connect(lambda _: self.apply_suggestion())
        self.suggestions.currentItemChanged.connect(self.suggestion_selected)
        dl.addWidget(self.suggestions, 1)
        self.suggestion_reason = label("Suggestions preserve your choice of wording.")
        self.suggestion_reason.setWordWrap(True)
        dl.addWidget(self.suggestion_reason)
        dl.addWidget(button("REPLACE SELECTED WORD", self.apply_suggestion))
        self.learn = QCheckBox("Learn this replacement")
        self.learn.setChecked(True)
        self.learn.setToolTip("Remember replacements you approve in this project.")
        dl.addWidget(self.learn)
        self.auto_correct = QCheckBox("Auto-correct learned typos")
        self.auto_correct.setToolTip(
            "Only applies replacements you have explicitly approved. Off by default."
        )
        self.auto_correct.toggled.connect(
            lambda checked: setattr(self.editor, "auto_correct", checked)
        )
        dl.addWidget(self.auto_correct)
        dl.addSpacing(8)
        dl.addWidget(label("PROJECT VOCABULARY", "section"))
        dl.addWidget(button("+  ADD WORD TO DICTIONARY", self.add_word, "flat"))
        self.personal_words = QComboBox()
        self.personal_words.setMinimumWidth(0)
        dl.addWidget(self.personal_words)
        dl.addWidget(button("REMOVE SELECTED WORD", self.remove_word, "flat"))
        dictionary_scroll = QScrollArea()
        dictionary_scroll.setWidgetResizable(True)
        dictionary_scroll.setFrameShape(QFrame.NoFrame)
        dictionary_scroll.setWidget(dictionary_panel)
        self.tabs.addTab(dictionary_scroll, "LEXICON")

        review_panel, rl = frame("review", margins=(12, 18, 12, 12))
        rl.addWidget(label("REVIEW QUEUE", "section"))
        review_hint = label("Uncertain OCR and unrecognized\nspellings. Click to inspect.")
        review_hint.setWordWrap(True)
        rl.addWidget(review_hint)
        self.review_list = QTreeWidget()
        self.review_list.setHeaderLabels(["TEXT", "REASON"])
        self.review_list.setRootIsDecorated(False)
        self.review_list.setColumnWidth(0, 120)
        self.review_list.itemClicked.connect(self.review_item_clicked)
        rl.addWidget(self.review_list, 1)
        rl.addWidget(label("OCR scores are engine estimates,\nnot guaranteed accuracy."))
        self.tabs.addTab(review_panel, "REVIEW")

        notes_panel, nl = frame("notesPanel", margins=(14, 18, 14, 14))
        nl.addWidget(label("PAGE NOTES", "section"))
        nl.addWidget(label("Record context, uncertain readings,\nand decisions for this page."))
        self.notes = QPlainTextEdit()
        self.notes.setObjectName("notes")
        self.notes.setPlaceholderText("[illegible] · possible name · context…")
        self.notes.textChanged.connect(self.notes_changed)
        nl.addWidget(self.notes, 1)
        self.tabs.addTab(notes_panel, "NOTES")

        metrics, ml = frame("footer", margins=(16, 18, 16, 18), spacing=10)
        ml.addWidget(label("SESSION OVERVIEW", "section"))
        self.time_estimate = label("—", "title")
        ml.addWidget(self.time_estimate)
        self.estimate_detail = label(f"Estimated review time · {self.review_wpm} wpm")
        self.estimate_detail.setWordWrap(True)
        ml.addWidget(self.estimate_detail)
        self.session_label = label("SESSION  0 MIN", "section")
        ml.addWidget(self.session_label)
        inspect.addWidget(metrics)
        main.addWidget(self.inspector)
        main.setSizes([225, 1000, 315])
        main.setStretchFactor(1, 1)

        self.storage_status = label("●  ON DEVICE   |   NO ACCOUNT REQUIRED", "muted")
        self.statusBar().addPermanentWidget(self.storage_status)
        self.setAcceptDrops(True)

    def _build_menus(self):
        self.file_menu = self.menuBar().addMenu("File")
        self.add_action(self.file_menu, "Import documents…", self.import_dialog, "Ctrl+O")
        self.add_action(
            self.file_menu, "Import clipboard image", self.import_clipboard, "Ctrl+Shift+V"
        )
        self.add_action(self.file_menu, "Open printed sample", self.open_sample)
        self.file_menu.addSeparator()
        self.add_action(self.file_menu, "New project…", lambda: self.switch_project(True))
        self.add_action(self.file_menu, "Open project…", lambda: self.switch_project(False))
        self.add_action(self.file_menu, "Back up project…", self.backup_project)
        self.file_menu.addSeparator()
        self.add_action(self.file_menu, "Save now", self.save_current, "Ctrl+S")
        self.add_action(self.file_menu, "Export current document…", self.export_current, "Ctrl+E")
        self.add_action(self.file_menu, "Rename document…", self.rename_document)
        self.add_action(self.file_menu, "Delete document…", self.delete_document)
        self.file_menu.addSeparator()
        self.add_action(self.file_menu, "Quit", self.close, "Ctrl+Q")
        edit = self.edit_menu = self.menuBar().addMenu("Edit")
        self.add_action(edit, "Undo", self.editor.undo, "Ctrl+Z")
        self.add_action(edit, "Redo", self.editor.redo, "Ctrl+Shift+Z")
        self.add_action(edit, "Find and replace", self.show_find, "Ctrl+F")
        self.add_action(edit, "Complete word", self.complete_word)
        self.add_action(
            edit, "Insert [illegible]", lambda: self.editor.insertPlainText("[illegible]"), "Ctrl+I"
        )
        view = self.menuBar().addMenu("View")
        self.add_action(view, "Fit source page", self.viewer.fit_page, "Ctrl+0")
        self.add_action(view, "Zoom in", lambda: self.viewer.zoom(1.2), "Ctrl+=")
        self.add_action(view, "Zoom out", lambda: self.viewer.zoom(1 / 1.2), "Ctrl+-")
        self.add_action(view, "Increase editor font", lambda: self.change_font(1))
        self.add_action(view, "Decrease editor font", lambda: self.change_font(-1))
        self.add_action(
            view,
            "Show / hide assistance",
            lambda: self.inspector.setVisible(not self.inspector.isVisible()),
            "Ctrl+Shift+A",
        )
        self.spell_action = QAction("Underline spelling issues", self)
        self.spell_action.setCheckable(True)
        self.spell_action.setChecked(True)
        self.spell_action.toggled.connect(self.toggle_spelling)
        view.addAction(self.spell_action)
        tools = self.tools_menu = self.menuBar().addMenu("Tools")
        self.add_action(tools, "Recognize page / region", self.recognize, "Ctrl+R")
        self.add_action(
            tools, "Recognize blank pages in document", self.recognize_batch, "Ctrl+Shift+R"
        )
        self.add_action(tools, "Download handwriting model…", self.install_model)
        self.add_action(tools, "Model library / offline packs…", self.show_models)
        self.add_action(tools, "Writing rules…", self.configure_rules)
        self.add_action(tools, "Review writing-rule changes…", self.check_rules, "Ctrl+Shift+K")
        self.add_action(tools, "Reset scan to original", lambda: self.process_image("reset"))
        self.add_action(tools, "Set review pace…", self.set_review_pace)
        self.add_action(tools, "Forget learned corrections…", self.forget_corrections)
        help_menu = self.menuBar().addMenu("Help")
        self.add_action(help_menu, "Keyboard shortcuts", self.show_shortcuts, "F1")
        self.add_action(help_menu, "About / engine requirements", self.show_about)

    def add_action(self, menu, title, callback, shortcut=None):
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def set_page_enabled(self, enabled):
        for widget in (
            self.editor,
            self.notes,
            self.reviewed,
            self.recognize_button,
            self.export_button,
            self.region_button,
            self.rotate_button,
            self.clean_button,
            self.check_rules_button,
        ):
            widget.setEnabled(enabled and not self.busy)

    def error(self, title, message):
        QMessageBox.warning(self, title, str(message))

    def refresh_library(self, select_page=None):
        if not hasattr(self, "library"):
            return
        current = select_page or (self.current_page.id if self.current_page else None)
        self.library.blockSignals(True)
        self.library.clear()
        documents = self.store.documents(self.library_search.text())
        selected = None
        for document in documents:
            title = document["title"]
            parent = QTreeWidgetItem([title])
            parent.setData(0, Qt.UserRole, ("document", document["id"]))
            parent.setToolTip(0, f"{title}\n{document['page_count']} page(s)")
            parent.setForeground(0, QColor("#e0e2e3"))
            self.library.addTopLevelItem(parent)
            for page in self.store.pages(document["id"]):
                marker = "✓" if page.reviewed else "▤"
                child = QTreeWidgetItem([f"{marker}  Page {page.number:02d}"])
                child.setData(0, Qt.UserRole, ("page", page.id))
                parent.addChild(child)
                if page.id == current:
                    selected = child
            parent.setExpanded(True)
        if selected:
            self.library.setCurrentItem(selected)
        self.library.blockSignals(False)
        all_docs = self.store.documents()
        self.library_count.setText(
            f"{len(all_docs):02d} DOCUMENTS  /  {sum(d['page_count'] for d in all_docs):02d} PAGES"
        )

    def library_selected(self):
        if self.busy:
            return
        items = self.library.selectedItems()
        if not items:
            return
        kind, identity = items[0].data(0, Qt.UserRole)
        if kind == "document":
            pages = self.store.pages(identity)
            if pages:
                identity = pages[0].id
        self.load_page(identity)

    def load_page(self, page_id, save=True):
        if save and not self.save_current():
            return
        page = self.store.page(page_id)
        try:
            self.viewer.load(page.image_path)
        except Exception as error:
            self.error("Image unavailable", error)
            return
        self.loading = True
        self.current_page = page
        self.tokens = page.tokens
        self.engine_name = page.engine
        self.previous_text = page.text
        self.editor.setPlainText(page.text)
        self.notes.setPlainText(page.notes)
        self.reviewed.setChecked(page.reviewed)
        self.viewer.tokens = self.tokens
        self.viewer.ordered_regions = self.store.preference("regions:" + page.id, [])
        self.viewer.viewport().update()
        self.loading = False
        document = next(d for d in self.store.documents() if d["id"] == page.document_id)
        self.document_title.setText(document["title"])
        self.document_subtitle.setText(
            f"Page {page.number} of {document['page_count']}  ·  {page.engine or 'Ready for transcription'}"
        )
        mode = self.store.preference("fidelity:" + page.id, {}).get("mode", "faithful")
        self.document_subtitle.setText(self.document_subtitle.text() + f" · Reading: {mode}")
        self.page_label.setText(f"PAGE {page.number:02d} / {document['page_count']:02d}")
        self.set_page_enabled(True)
        self.save_status.setText("SAVED LOCALLY")
        self.refresh_library(page.id)
        self.refresh_review()
        self.update_metrics()

    def text_changed(self):
        if self.loading or not self.current_page:
            return
        text = self.editor.toPlainText()
        self.tokens = shift_tokens(self.tokens, self.previous_text, text)
        self.previous_text = text
        self.viewer.tokens = self.tokens
        self.viewer.active_box = None
        self.viewer.viewport().update()
        if self.reviewed.isChecked():
            self.reviewed.setChecked(False)
        self.queue_save()
        self.inspection_timer.start()
        self.update_metrics()

    def notes_changed(self):
        if not self.loading and self.current_page:
            self.queue_save()

    def review_toggled(self, _):
        if not self.loading and self.current_page:
            self.queue_save()
            self.update_metrics()

    def queue_save(self):
        self.save_status.setText("UNSAVED CHANGES")
        self.autosave.start()

    def save_current(self):
        if not hasattr(self, "autosave") or not self.current_page or self.loading:
            return True
        self.autosave.stop()
        try:
            self.store.save_page(
                self.current_page.id,
                self.editor.toPlainText(),
                self.tokens,
                self.notes.toPlainText(),
                self.reviewed.isChecked(),
                self.engine_name,
                getattr(self, "edit_source", "manual"),
            )
            state = self.store.preference("fidelity:" + self.current_page.id)
            if state:
                state[state["mode"]] = self.editor.toPlainText()
                self.store.set_preference("fidelity:" + self.current_page.id, state)
            self.edit_source = "manual"
            self.dictionary.context.update(
                self.current_page.id, self.editor.toPlainText(), self.reviewed.isChecked()
            )
            self.save_status.setText("SAVED LOCALLY")
            self.refresh_library()
            return True
        except Exception as error:
            self.save_status.setText("SAVE FAILED")
            self.error("Could not save — your text is still in the editor", error)
            return False

    def update_metrics(self):
        text = self.editor.toPlainText()
        stats = estimate(
            text, self.reviewed.isChecked(), self.review_wpm, time.monotonic() - self.started
        )
        self.word_count.setText(f"{stats['words']} WORDS  /  {len(text)} CHARS")
        if self.current_page:
            self.time_estimate.setText(
                "REVIEWED ✓" if self.reviewed.isChecked() else f"~{stats['minutes']:g} min"
            )
        else:
            self.time_estimate.setText("—")
        self.estimate_detail.setText(
            f"Estimated page review · {self.review_wpm} wpm\nAdjust pace in Tools. Text required."
        )
        self.session_label.setText(f"SESSION  {stats['session_minutes']:g} MIN")

    def region_changed(self, region):
        self.region_label.setText("REGION → INSERT" if region else "FULL PAGE")
        self.region_label.setToolTip(
            "Region OCR inserts at the editor cursor. Full-page OCR replaces page text after confirmation."
        )

    def select_token(self, index):
        if index >= len(self.tokens):
            return
        token = self.tokens[index]
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        cursor.setPosition(py_to_qt(text, token["start"]))
        cursor.setPosition(py_to_qt(text, token["end"]), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.viewer.active_box = token["box"]
        self.viewer.viewport().update()
        self.cursor_changed()

    def cursor_changed(self):
        if self.loading:
            return
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        position = qt_to_py(
            text, cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        )
        token = next((t for t in self.tokens if t["start"] <= position < t["end"]), None)
        self.viewer.active_box = token["box"] if token else None
        self.viewer.viewport().update()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText().strip()
        if WORD_RE.fullmatch(word):
            self.lookup.setText(word)
            # Debounced to avoid running edit-distance searches on every cursor move.
            if not hasattr(self, "lookup_timer"):
                self.lookup_timer = QTimer(self)
                self.lookup_timer.setSingleShot(True)
                self.lookup_timer.timeout.connect(self.lookup_word)
            self.lookup_timer.start(180)

    def lookup_word(self):
        word = self.lookup.text().strip()
        self.suggestions.clear()
        if not WORD_RE.fullmatch(word):
            self.lookup_status.setText("ENTER A SINGLE WORD")
            return
        known = self.dictionary.known(word)
        self.lookup_status.setText("IN YOUR DICTIONARY" if known else "SPELLING NOT RECOGNIZED")
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        before, after = "", ""
        if cursor.selectedText().casefold() == word.casefold():
            start, end = (
                qt_to_py(text, cursor.selectionStart()),
                qt_to_py(text, cursor.selectionEnd()),
            )
            before, after = text[:start], text[end:]
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", end)
            if line_end < 0:
                line_end = len(text)
            excerpt = (
                text[max(line_start, start - 45) : start]
                + "["
                + word
                + "]"
                + text[end : min(line_end, end + 45)]
            )
            self.context_hint.setText(excerpt.replace("\n", " "))
        else:
            self.context_hint.setText(
                "Standalone lookup · select a word in the editor for sentence-aware ranking."
            )
        ranked = self.dictionary.rank(word, before, after, self.context_enabled.isChecked())
        for suggestion in ranked:
            item = QListWidgetItem(suggestion.word)
            item.setData(Qt.UserRole, suggestion.reason)
            item.setToolTip(suggestion.reason)
            if suggestion.context_evidence:
                item.setForeground(QColor("#f5a469"))
            self.suggestions.addItem(item)
        if self.suggestions.count():
            self.suggestions.setCurrentRow(0)

    def suggestion_selected(self, item, _previous):
        if hasattr(self, "suggestion_reason"):
            self.suggestion_reason.setText(
                item.data(Qt.UserRole) if item else "No close alternatives found."
            )

    def context_changed(self, checked):
        self.store.set_preference("context_enabled", checked)
        self.lookup_word()

    def configure_rules(self):
        if self.busy:
            return False
        dialog = RulesDialog(
            self.store.writing_rules(),
            self.editor.toPlainText()[:5000],
            self,
            review_on_export=self.store.preference("review_rules_on_export", True),
        )
        if dialog.exec() != QDialog.Accepted:
            return False
        self.store.save_rules(dialog.rules)
        self.store.set_preference("review_rules_on_export", dialog.review_on_export.isChecked())
        count = sum(rule.enabled for rule in dialog.rules)
        self.rules_button.setText(f"RULES & STYLE · {count}")
        self.statusBar().showMessage(
            f"Saved {count} enabled writing rule(s) for this project. Use CHECK RULES to review changes."
        )
        return True

    def check_rules(self):
        if self.busy or not self.current_page:
            return False
        rules = self.effective_rules()
        if not any(rule.enabled for rule in rules):
            if not self.configure_rules():
                return False
            rules = self.effective_rules()
        try:
            preview = preview_rules(self.editor.toPlainText(), rules)
        except ValueError as error:
            self.error("Check writing rules", error)
            return False
        if not preview.edits:
            self.statusBar().showMessage("No changes proposed by the enabled writing rules.", 5000)
            return True
        dialog = RuleReviewDialog(preview, self)
        if dialog.exec() == QDialog.Accepted:
            return self.apply_rule_edits(preview.before, dialog.selected_edits())
        return False

    def apply_rule_edits(self, before, edits):
        if self.busy or not self.current_page or self.editor.toPlainText() != before:
            self.statusBar().showMessage(
                "The text changed. Check the rules again before applying changes."
            )
            return False
        if not edits:
            self.statusBar().showMessage("Kept original wording.", 5000)
            return True
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        tokens, working = self.tokens, before
        for edit in reversed(edits):
            cursor.setPosition(py_to_qt(before, edit.start))
            cursor.setPosition(py_to_qt(before, edit.end), QTextCursor.KeepAnchor)
            cursor.insertText(edit.replacement)
            after = working[: edit.start] + edit.replacement + working[edit.end :]
            tokens = shift_tokens(tokens, working, after)
            working = after
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.tokens = tokens
        self.viewer.tokens = tokens
        self.viewer.viewport().update()
        self.queue_save()
        self.refresh_review()
        self.statusBar().showMessage(
            f"Applied {len(edits)} writing-rule change(s). Ctrl+Z to undo."
        )
        self.edit_source = "writing rules"
        return True

    def show_models(self):
        if self.busy:
            return
        dialog = ModelLibraryDialog(self.model_dir, self)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.operation == "download":
            self.install_model()
        elif dialog.operation == "import":
            self._run_job(
                lambda cancel, progress: install_pack(
                    dialog.path, self.model_dir, cancel, progress
                ),
                lambda _: self.statusBar().showMessage(
                    "Verified model pack installed. Handwriting weights are available offline."
                ),
            )
        elif dialog.operation == "export":
            self._run_job(
                lambda cancel, progress: export_pack(self.model_dir, dialog.path, cancel, progress),
                lambda path: self.statusBar().showMessage(f"Offline model pack exported to {path}"),
            )

    def apply_suggestion(self):
        item = self.suggestions.currentItem()
        if not item or not self.current_page or self.busy:
            return
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        original = cursor.selectedText()
        if original.casefold() != self.lookup.text().strip().casefold():
            self.statusBar().showMessage(
                "Select the word to replace in the transcription first.", 5000
            )
            return
        replacement = item.text()
        if original.isupper():
            replacement = replacement.upper()
        elif original[:1].isupper():
            replacement = replacement.capitalize()
        if self.learn.isChecked():
            self.learn_writer_correction(original, item.text())
            self.dictionary.learned[original.casefold()] = item.text()
            self.dictionary.candidates.cache_clear()
        cursor.insertText(replacement)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.edit_source = "dictionary"

    def add_word(self):
        word = self.lookup.text().strip()
        if not WORD_RE.fullmatch(word):
            self.error(
                "Choose a word",
                "Enter or select a single word to add to this project's vocabulary.",
            )
            return
        self.store.add_word(word)
        self.reload_dictionary()
        self.lookup_word()

    def remove_word(self):
        word = self.personal_words.currentText()
        if word:
            self.store.remove_word(word)
            self.reload_dictionary()

    def reload_dictionary(self):
        self.dictionary = Dictionary(
            self.store.vocabulary() + self.profile_words(),
            self.profile_corrections(),
            self.store.reviewed_texts(),
        )
        self.editor.dictionary = self.dictionary
        self.highlighter.dictionary = self.dictionary
        self.highlighter.rehighlight()
        self.refresh_vocabulary()
        self.refresh_review()

    def refresh_vocabulary(self):
        self.personal_words.clear()
        self.personal_words.addItems(self.store.vocabulary())
        self.personal_words.setPlaceholderText("No personal words yet")

    def refresh_review(self):
        self.review_list.clear()
        if not self.current_page:
            self.tabs.setTabText(1, "REVIEW")
            return
        entries = []
        for index, token in enumerate(self.tokens):
            confidence = token.get("confidence")
            if confidence is None or confidence < 75:
                entries.append(
                    (
                        token["text"],
                        "Unscored" if confidence is None else f"OCR {confidence:g}",
                        ("token", index),
                    )
                )
        seen = set()
        text = self.editor.toPlainText()
        for match in WORD_RE.finditer(text):
            word = match.group()
            if word.casefold() not in seen and not self.dictionary.known(word):
                entries.append((word, "Spelling", ("word", match.start(), match.end())))
                seen.add(word.casefold())
        for text, reason, data in entries:
            item = QTreeWidgetItem([text, reason])
            item.setData(0, Qt.UserRole, data)
            item.setToolTip(0, text)
            self.review_list.addTopLevelItem(item)
        self.tabs.setTabText(1, f"REVIEW {len(entries):02d}")

    def review_item_clicked(self, item, _):
        data = item.data(0, Qt.UserRole)
        if data[0] == "token":
            self.select_token(data[1])
        else:
            cursor = self.editor.textCursor()
            text = self.editor.toPlainText()
            cursor.setPosition(py_to_qt(text, data[1]))
            cursor.setPosition(py_to_qt(text, data[2]), QTextCursor.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def _run_job(self, function, success, cleanup=None):
        if self.busy:
            return
        if not self.save_current():
            if cleanup:
                cleanup()
            return
        self.busy = True
        self.job_success = success
        self.job_cleanup = cleanup
        self.job = Job(function)
        self.job.signals.progress.connect(self.job_progress)
        self.job.signals.done.connect(self.job_done)
        self.library.setEnabled(False)
        self.inspector.setEnabled(False)
        self.file_menu.setEnabled(False)
        self.edit_menu.setEnabled(False)
        self.tools_menu.setEnabled(False)
        self.advanced_menu.setEnabled(False)
        if hasattr(self, "lookup_timer"):
            self.lookup_timer.stop()
        self.engine.setEnabled(False)
        self.viewer.setEnabled(False)
        self.set_page_enabled(False)
        self.cancel_button.show()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.thread_pool.start(self.job)

    def job_progress(self, message):
        self.statusBar().showMessage(message)

    def job_done(self, result, error, cancelled):
        callback, cleanup = self.job_success, self.job_cleanup
        self.job = None
        self.job_success = None
        self.job_cleanup = None
        self.busy = False
        self.library.setEnabled(True)
        self.inspector.setEnabled(True)
        self.file_menu.setEnabled(True)
        self.edit_menu.setEnabled(True)
        self.tools_menu.setEnabled(True)
        self.advanced_menu.setEnabled(True)
        self.engine.setEnabled(True)
        self.viewer.setEnabled(True)
        self.cancel_button.hide()
        self.progress.hide()
        self.set_page_enabled(bool(self.current_page))
        try:
            if cancelled:
                self.statusBar().showMessage(
                    "Operation cancelled. Existing transcription was preserved."
                )
            elif error:
                self.statusBar().showMessage(
                    "Operation failed. Existing transcription was preserved."
                )
                self.error("Could not complete operation", error)
            elif callback:
                callback(result)
        except Exception as exception:
            self.error("Could not apply result", exception)
        finally:
            if self.active_queue_id is not None:
                self.queue_result(error, cancelled)
            if cleanup:
                cleanup()

    def cancel_job(self):
        if self.job:
            self.job.cancel.set()
            self.statusBar().showMessage(
                "Cancellation requested · waiting for the current OCR call or download to stop…"
            )

    def import_dialog(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import documents",
            "",
            "Documents (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;All files (*)",
        )
        if paths:
            self.import_paths([Path(p) for p in paths])

    def import_paths(self, paths, after=None):
        if self.busy:
            return
        staging = Path(tempfile.mkdtemp(prefix="import-", dir=self.data_dir))

        def success(documents):
            first_page = None
            for document in documents:
                identity = self.store.add_document(document.title, document.source, document.images)
                first_page = first_page or self.store.pages(identity)[0].id
            self.refresh_library(first_page)
            if first_page:
                self.load_page(first_page)
            self.statusBar().showMessage(
                f"Imported {len(documents)} document(s). Originals preserved locally."
            )
            if after:
                after()

        self._run_job(
            lambda cancel, progress: import_files(paths, staging, cancel, progress),
            success,
            lambda: shutil.rmtree(staging, ignore_errors=True),
        )

    def open_sample(self):
        if self.busy:
            return
        path = self.data_dir / "samples" / "Field notes (printed sample).png"
        make_sample(path)
        self.import_paths([path])

    def import_clipboard(self):
        if self.busy:
            return
        image = QApplication.clipboard().image()
        if image.isNull():
            self.error("No image on clipboard", "Copy an image or screenshot, then try again.")
            return
        path = self.data_dir / "clipboard.png"
        if not image.save(str(path), "PNG"):
            self.error("Clipboard import failed", "Could not save the image.")
            return
        self.import_paths([path], after=lambda: path.unlink(missing_ok=True))

    def recognize(self):
        if self.busy or not self.current_page:
            return
        region = self.viewer.region_tuple()
        if self.editor.toPlainText().strip() and not region:
            answer = QMessageBox.question(
                self,
                "Replace page transcription?",
                "Full-page OCR replaces the text on this page. You can undo the replacement. "
                "Choose a region to insert text instead.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        path = self.current_page.image_path
        insertion = self.editor.textCursor()
        handwriting = self.engine.currentIndex() == 1

        def function(cancel, progress):
            if handwriting:
                return handwritten_ocr(path, region, self.model_dir, cancel, progress)
            return printed_ocr(path, region, cancel, progress)

        def success(result):
            if not result.text:
                self.statusBar().showMessage(
                    "No text detected. Try cleaning the scan or selecting a single line."
                )
                return
            if region:
                start = qt_to_py(self.editor.toPlainText(), insertion.selectionStart())
                insertion.beginEditBlock()
                insertion.insertText(result.text)
                insertion.endEditBlock()
                self.editor.setTextCursor(insertion)
                for token in result.tokens:
                    token = dict(token)
                    token["start"] += start
                    token["end"] += start
                    self.tokens.append(token)
                self.tokens.sort(key=lambda token: token["start"])
            else:
                cursor = self.editor.textCursor()
                cursor.beginEditBlock()
                cursor.select(QTextCursor.Document)
                cursor.insertText(result.text)
                cursor.endEditBlock()
                self.editor.setTextCursor(cursor)
                self.tokens = result.tokens
            self.engine_name = result.engine
            self.edit_source = "OCR"
            self.viewer.tokens = self.tokens
            self.viewer.viewport().update()
            self.document_subtitle.setText(f"Page {self.current_page.number}  ·  {result.engine}")
            self.queue_save()
            self.refresh_review()
            self.statusBar().showMessage(
                f"Recognized {len(WORD_RE.findall(result.text))} words locally. Review before exporting."
            )

        self._run_job(function, success)

    def process_image(self, operation):
        if self.busy or not self.current_page:
            return
        if not self.save_current():
            return
        try:
            if operation == "reset":
                target = self.current_page.original_path
            else:
                with Image.open(self.current_page.image_path) as source:
                    image = source.convert("RGB")
                if operation == "rotate":
                    image = image.transpose(Image.Transpose.ROTATE_270)
                else:
                    image = ImageOps.autocontrast(ImageOps.grayscale(image)).filter(
                        ImageFilter.MedianFilter(3)
                    )
                target = (
                    self.store.root / "images" / f"{self.current_page.id}-{uuid4().hex[:8]}.png"
                )
                image.save(target)
            self.store.set_preference("regions:" + self.current_page.id, [])
            self.store.set_preference("lines:" + self.current_page.id, {})
            self.store.set_image(self.current_page.id, target)
            # Prevent load_page's pre-save from restoring obsolete OCR coordinates.
            self.tokens = []
            self.load_page(self.current_page.id)
            self.reviewed.setChecked(False)
            self.queue_save()
            self.statusBar().showMessage(
                "Scan updated. Transcription preserved; OCR alignment cleared. Original is available in Tools."
            )
        except Exception as error:
            self.error("Could not process scan", error)

    def recognize_batch(self):
        if self.busy or not self.current_page or not self.save_current():
            return
        pages = [
            page
            for page in self.store.pages(self.current_page.document_id)
            if not page.text.strip()
        ]
        if not pages:
            self.statusBar().showMessage(
                "No blank pages in this document. Existing transcriptions are preserved.", 5000
            )
            return
        handwriting = self.engine.currentIndex() == 1
        selected_id = self.current_page.id

        def function(cancel, progress):
            from .documents import check_cancel

            results = []
            for index, page in enumerate(pages):
                check_cancel(cancel)

                def page_progress(message, index=index):
                    progress(f"Page {index + 1}/{len(pages)} · {message}")

                result = (
                    handwritten_ocr(page.image_path, None, self.model_dir, cancel, page_progress)
                    if handwriting
                    else printed_ocr(page.image_path, None, cancel, page_progress)
                )
                results.append((page.id, result))
            return results

        def success(results):
            self.store.save_ocr_batch(results)
            self.load_page(selected_id, save=False)
            count = sum(bool(result.text) for _, result in results)
            self.statusBar().showMessage(
                f"Recognized {count} of {len(results)} blank pages. Existing transcriptions preserved."
            )

        self._run_job(function, success)

    def export_current(self):
        if self.busy or not self.current_page or not self.save_current():
            return
        if self.store.preference("review_rules_on_export", True) and any(
            rule.enabled for rule in self.effective_rules()
        ):
            if not self.review_document_rules() or not self.save_current():
                return
        title = self.document_title.text()
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export entire document",
            f"{title}.txt",
            "Plain text (*.txt);;Markdown (*.md);;Word document (*.docx);;Structured JSON (*.json);;Searchable PDF (*.pdf)",
        )
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            extension = {
                "Plain text": ".txt",
                "Markdown": ".md",
                "Word document": ".docx",
                "Structured JSON": ".json",
                "Searchable PDF": ".pdf",
            }
            destination = destination.with_suffix(
                next(v for k, v in extension.items() if selected_filter.startswith(k))
            )
            if (
                destination.exists()
                and QMessageBox.question(
                    self,
                    "Replace existing export?",
                    f"Replace {destination.name}?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
        try:
            export_document(self.store.pages(self.current_page.document_id), destination, title)
            self.statusBar().showMessage(f"Exported document to {destination}")
        except Exception as error:
            self.error("Export failed", error)

    def review_document_rules(self):
        original_page_id = self.current_page.id
        document_id = self.current_page.document_id
        rules = self.effective_rules()
        try:
            for page in self.store.pages(document_id):
                if not preview_rules(page.text, rules).edits:
                    continue
                if self.current_page.id != page.id:
                    self.load_page(page.id)
                if not self.check_rules() or not self.save_current():
                    self.statusBar().showMessage(
                        "Export cancelled. Changes you already approved remain saved."
                    )
                    return False
            return True
        except ValueError as error:
            self.error("Check writing rules", error)
            return False
        finally:
            if self.current_page.id != original_page_id:
                self.load_page(original_page_id)

    def switch_project(self, new):
        if self.busy or not self.save_current():
            return
        root = QFileDialog.getExistingDirectory(
            self, "Choose a new empty folder" if new else "Open project folder"
        )
        if not root:
            return
        path = Path(root)
        if path.resolve() == self.store.root:
            return
        if new and any(path.iterdir()):
            self.error("Choose an empty folder", "A new project needs its own empty folder.")
            return
        if not new and not (path / "project.sqlite3").is_file():
            self.error("Project not found", "Choose a folder containing project.sqlite3.")
            return
        try:
            self._open_store(path)
        except Exception as error:
            self.error("Could not open project", error)
            return
        self.queue_paused = True
        with self.store.db:
            self.store.db.execute("UPDATE queue SET status='queued' WHERE status='running'")
        self.apply_accessibility()
        self.current_page = None
        self.tokens = []
        self.previous_text = ""
        self.editor.clear()
        self.notes.clear()
        self.reviewed.setChecked(False)
        self.viewer.clear()
        self.lookup.clear()
        self.suggestions.clear()
        self.library_search.clear()
        self.reload_dictionary()
        self.context_enabled.blockSignals(True)
        self.context_enabled.setChecked(self.store.preference("context_enabled", True))
        self.context_enabled.blockSignals(False)
        self.rules_button.setText(
            f"RULES & STYLE · {sum(rule.enabled for rule in self.store.writing_rules())}"
        )
        self.project_label.setText(path.name.upper())
        self.project_label.setToolTip(str(path))
        self.document_title.setText("Make every word readable.")
        self.document_subtitle.setText("Import a scan. Recognize the text. Make it yours.")
        self.page_label.setText("NO PAGE SELECTED")
        self.refresh_library()
        self.set_page_enabled(False)
        self.update_metrics()

    def backup_project(self):
        if self.busy or not self.save_current():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up project", "transcription-backup.zip", "ZIP archive (*.zip)"
        )
        if not path:
            return
        import sqlite3

        try:
            with tempfile.TemporaryDirectory(dir=self.data_dir) as temporary:
                database = Path(temporary) / "project.sqlite3"
                connection = sqlite3.connect(database)
                try:
                    self.store.db.backup(connection)
                finally:
                    connection.close()
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(database, "project.sqlite3")
                    for image in (self.store.root / "images").glob("*.png"):
                        archive.write(image, f"images/{image.name}")
            self.statusBar().showMessage(
                "Project backed up. To restore, extract into a new folder and choose File → Open project."
            )
        except Exception as error:
            self.error("Backup failed", error)

    def rename_document(self):
        if not self.current_page or self.busy:
            return
        title, ok = QInputDialog.getText(
            self, "Rename document", "Document title:", text=self.document_title.text()
        )
        if ok and title.strip():
            self.store.rename_document(self.current_page.document_id, title)
            self.document_title.setText(title.strip())
            self.refresh_library()

    def delete_document(self):
        if not self.current_page or self.busy:
            return
        answer = QMessageBox.question(
            self,
            "Delete document?",
            "Delete this document, its pages, and its transcription from this project? "
            "The source file outside the project will not be changed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.autosave.stop()
        self.store.delete_document(self.current_page.document_id)
        self.current_page = None
        self.tokens = []
        self.editor.clear()
        self.notes.clear()
        self.reviewed.setChecked(False)
        self.viewer.clear()
        self.refresh_library()
        self.refresh_review()
        self.document_title.setText("Make every word readable.")
        self.document_subtitle.setText("Import a scan. Recognize the text. Make it yours.")
        self.page_label.setText("NO PAGE SELECTED")
        self.set_page_enabled(False)
        self.update_metrics()

    def show_find(self):
        self.search_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def find_next(self):
        needle = self.find_input.text()
        if not needle:
            return
        found = self.editor.find(needle)
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(needle)
        self.statusBar().showMessage(
            "Match selected." if found else "No matches on this page.", 3000
        )

    def replace_all(self):
        if not self.current_page or self.busy:
            return
        needle = self.find_input.text()
        if not needle:
            return
        document = self.editor.document()
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        found = document.find(needle, 0)
        count = 0
        while not found.isNull():
            found.insertText(self.replace_input.text())
            count += 1
            found = document.find(needle, found.position())
        cursor.endEditBlock()
        self.statusBar().showMessage(f"Replaced {count} occurrence(s). Ctrl+Z to undo.")

    def complete_word(self):
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        words = self.dictionary.complete(cursor.selectedText())
        if words:
            word, ok = QInputDialog.getItem(self, "Complete word", "Suggestions:", words, 0, False)
            if ok:
                self.editor.insert_completion(word)

    def toggle_spelling(self, checked):
        self.highlighter.enabled = checked
        self.highlighter.rehighlight()

    def change_font(self, delta):
        font = self.editor.font()
        font.setPointSize(max(9, min(28, font.pointSize() + delta)))
        self.editor.setFont(font)
        self.editor.update_gutter()

    def set_review_pace(self):
        pace, ok = QInputDialog.getInt(
            self, "Review pace", "Words reviewed per minute (estimate):", self.review_wpm, 5, 300
        )
        if ok:
            self.review_wpm = pace
            self.settings.setValue("review_wpm", pace)
            self.update_metrics()

    def forget_corrections(self):
        if self.busy:
            return
        if (
            QMessageBox.question(
                self,
                "Forget corrections?",
                "Remove all learned typo replacements in this project? "
                "Your vocabulary and documents are preserved.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.store.forget_corrections()
            self.dictionary.learned.clear()

    def install_model(self):
        if self.busy:
            return
        if (
            QMessageBox.question(
                self,
                "Download local handwriting model",
                "Download Microsoft's TrOCR handwriting model "
                "from Hugging Face (~247 MB)? This downloads model files only; your documents stay on your device. "
                "The pinned files are checksum-verified before loading. Install handwriting dependencies first; see README.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self._run_job(
            lambda cancel, progress: download_handwriting_model(self.model_dir, cancel, progress),
            lambda _: self.statusBar().showMessage(
                "Handwriting model ready. Select Handwriting · TrOCR, then recognize a single line."
            ),
        )

    def show_shortcuts(self):
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "Ctrl+O       Import documents\nCtrl+R       Recognize page or region\nCtrl+S       Save immediately\n"
            "Ctrl+E       Export document\nCtrl+F       Find and replace\nCtrl+Space   Complete a word\n"
            "Ctrl+I       Insert [illegible]\nCtrl+Z       Undo\nCtrl+Shift+Z Redo\n"
            "Ctrl+0       Fit original page\nCtrl+scroll  Zoom original page\nCtrl+Shift+V Import clipboard image\n"
            "Ctrl+Shift+A Toggle assistance\n\nClick an OCR word in the scan to select its text.\n"
            "Select region → drag around one line → Recognize.\nRegion OCR replaces the editor selection or inserts at its cursor.",
        )

    def show_about(self):
        QMessageBox.information(
            self,
            "Document Transcriber 0.3",
            "Local-first transcription for Linux / ChromeOS Crostini.\n\n"
            "Printed OCR: Tesseract must be installed (sudo apt install tesseract-ocr).\n"
            "Handwriting: optional CPU PyTorch + Transformers and a one-time TrOCR model download. "
            "Single-line selections work best. Full-page line splitting is experimental.\n\n"
            "The dictionary ranks similar words using local English n-grams and your reviewed pages. "
            "It learns approved replacements. Context scores are statistical suggestions, not a guarantee of meaning.\n\n"
            "OCR scores and review times are estimates. Keep original scans and review the transcription.\n\n"
            f"Project: {self.store.root}\nModels: {self.model_dir}",
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths and not self.busy:
            self.import_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        if self.busy:
            self.cancel_job()
            self.statusBar().showMessage(
                "Waiting for the operation to stop. Close the window again when it finishes."
            )
            event.ignore()
            return
        if not self.save_current():
            event.ignore()
            return
        self.session_timer.stop()
        self.inspection_timer.stop()
        if hasattr(self, "lookup_timer"):
            self.lookup_timer.stop()
        self.settings.sync()
        self.store.close()
        self.project_lock.unlock()
        self._closed = True
        event.accept()
