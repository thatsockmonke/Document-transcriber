import time

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from document_transcriber.app import MainWindow, py_to_qt, qt_to_py
from document_transcriber.documents import make_sample
from document_transcriber.ocr import OcrResult


def wait_until(application, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if condition():
            return
        QTest.qWait(10)
    raise AssertionError("Timed out waiting for background operation")


def test_complete_gui_workflow(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    errors = []
    window.error = lambda title, message: errors.append((title, str(message)))
    window.show()
    sample = tmp_path / "Notebook.png"
    make_sample(sample)
    window.import_paths([sample])
    wait_until(qt_app, lambda: not window.busy)
    assert window.current_page is not None
    assert window.editor.isEnabled()
    page_id = window.current_page.id
    window.recognize()
    wait_until(qt_app, lambda: not window.busy)
    assert "FIELD NOTES" in window.editor.toPlainText()
    assert window.tokens
    first = window.tokens[0]
    window.select_token(0)
    assert window.editor.textCursor().selectedText() == first["text"]
    assert window.viewer.active_box == first["box"]
    window.editor.moveCursor(QTextCursor.End)
    window.editor.insertPlainText("\ntranscripton")
    cursor = window.editor.textCursor()
    cursor.select(QTextCursor.WordUnderCursor)
    window.editor.setTextCursor(cursor)
    window.lookup.setText("transcripton")
    window.lookup_word()
    assert window.suggestions.count() > 0
    transcription = next(
        i
        for i in range(window.suggestions.count())
        if window.suggestions.item(i).text() == "transcription"
    )
    window.suggestions.setCurrentRow(transcription)
    window.apply_suggestion()
    assert window.editor.toPlainText().endswith("transcription")
    assert window.store.corrections()["transcripton"] == "transcription"
    window.notes.setPlainText("Review the last line")
    window.reviewed.setChecked(True)
    QTest.qWait(750)
    qt_app.processEvents()
    assert window.store.page(page_id).reviewed
    assert window.store.page(page_id).notes == "Review the last line"
    assert "REVIEWED" in window.time_estimate.text()
    original = window.current_page.original_path.read_bytes()
    old_size = Image.open(window.current_page.image_path).size
    window.process_image("rotate")
    assert Image.open(window.current_page.image_path).size == old_size[::-1]
    assert window.current_page.original_path.read_bytes() == original
    assert not window.tokens
    assert window.editor.toPlainText().endswith("transcription")
    window.process_image("reset")
    assert window.current_page.image_path == window.current_page.original_path
    saved_text = window.editor.toPlainText()
    window.close()
    qt_app.processEvents()
    assert not errors
    reopened = MainWindow(tmp_path / "data")
    reopened.load_page(page_id)
    assert reopened.editor.toPlainText() == saved_text
    assert reopened.notes.toPlainText() == "Review the last line"
    reopened.close()


def test_learned_autocorrect_completion_and_unicode(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Notes", str(sample), [sample])
    window.load_page(window.store.pages(identity)[0].id)
    window.show()
    window.dictionary.learned["teh"] = "the"
    window.auto_correct.setChecked(True)
    window.editor.setPlainText("🦊 teh")
    window.editor.moveCursor(QTextCursor.End)
    QTest.keyClick(window.editor, Qt.Key_Space)
    assert window.editor.toPlainText() == "🦊 the "
    window.editor.setPlainText("docum")
    window.editor.moveCursor(QTextCursor.End)
    QTest.keyClick(window.editor, Qt.Key_Space, Qt.ControlModifier)
    assert window.editor.completer.popup().isVisible()
    window.editor.completer.popup().hide()
    window.editor.insert_completion("document")
    assert window.editor.toPlainText() == "document"
    text = "🦊 café"
    assert py_to_qt(text, 2) == 3
    assert qt_to_py(text, 3) == 2
    window.close()


def test_region_insertion_is_undoable_and_preserves_existing_text(qt_app, tmp_path, monkeypatch):
    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Notes", str(sample), [sample])
    window.load_page(window.store.pages(identity)[0].id)
    window.editor.insertPlainText("Original ")
    from PySide6.QtCore import QRectF

    window.viewer.region = QRectF(10, 20, 100, 30)
    result = OcrResult(
        "new text",
        [{"text": "new", "start": 0, "end": 3, "box": [10, 20, 35, 30], "confidence": 90}],
        "test",
    )
    monkeypatch.setattr("document_transcriber.app.printed_ocr", lambda *args: result)
    window.recognize()
    wait_until(qt_app, lambda: not window.busy)
    assert window.editor.toPlainText() == "Original new text"
    assert window.tokens[0]["start"] == 9
    window.editor.undo()
    assert window.editor.toPlainText() == "Original "
    window.close()


def test_project_lock_prevents_two_writers(qt_app, tmp_path):
    import pytest

    window = MainWindow(tmp_path / "data")
    with pytest.raises(RuntimeError, match="already open"):
        MainWindow(tmp_path / "data")
    window.close()


def test_batch_ocr_preserves_manually_transcribed_pages(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    errors = []
    window.error = lambda title, message: errors.append(str(message))
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Notes", str(sample), [sample, sample, sample])
    pages = window.store.pages(identity)
    window.store.save_page(
        pages[0].id, "Careful manual transcription", [], "Keep this", True, "manual"
    )
    window.load_page(pages[1].id)
    window.recognize_batch()
    wait_until(qt_app, lambda: not window.busy)
    pages = window.store.pages(identity)
    assert pages[0].text == "Careful manual transcription"
    assert pages[0].reviewed
    assert all("FIELD NOTES" in p.text for p in pages[1:])
    assert "FIELD NOTES" in window.editor.toPlainText()
    assert not errors
    window.close()


def test_cancel_and_failed_import_leave_editor_usable(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    errors = []
    window.error = lambda title, message: errors.append(str(message))
    applied = []

    def operation(cancel, progress):
        progress("Running cancellable operation")
        cancel.wait(5)
        return "discard this result"

    window._run_job(operation, applied.append)
    assert window.busy
    window.cancel_job()
    wait_until(qt_app, lambda: not window.busy)
    assert applied == []
    bad_file = tmp_path / "corrupted.pdf"
    bad_file.write_bytes(b"not a pdf")
    window.import_paths([bad_file])
    wait_until(qt_app, lambda: not window.busy)
    assert len(errors) == 1
    assert window.store.documents() == []
    assert not list(window.data_dir.glob("import-*"))
    assert window.file_menu.isEnabled()
    window.close()


def test_backup_is_consistent_with_autosaved_project(qt_app, tmp_path, monkeypatch):
    import sqlite3
    import zipfile

    from PySide6.QtWidgets import QFileDialog

    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    identity = window.store.add_document("Notes", str(sample), [sample])
    window.load_page(window.store.pages(identity)[0].id)
    window.editor.insertPlainText("Not yet autosaved")
    destination = tmp_path / "backup.zip"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), "ZIP archive (*.zip)")
    )
    window.backup_project()
    with zipfile.ZipFile(destination) as archive:
        assert any(p.startswith("images/") for p in archive.namelist())
        archive.extractall(tmp_path / "restored")
    db = sqlite3.connect(tmp_path / "restored" / "project.sqlite3")
    assert db.execute("SELECT text FROM pages").fetchone()[0] == "Not yet autosaved"
    db.close()
    window.close()
