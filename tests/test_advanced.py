import time

import pymupdf
import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog

from document_transcriber.advanced_ui import (
    LineDialog,
    PreferencesDialog,
    ProfileDialog,
    ReadingDialog,
)
from document_transcriber.app import MainWindow
from document_transcriber.dictionary import Dictionary
from document_transcriber.documents import export_document, make_sample
from document_transcriber.ocr import OcrResult
from document_transcriber.rules import WritingRule, preview_rules
from document_transcriber.workspace_tools import (
    comparison,
    deskew,
    perspective,
    phrase_suggestions,
    suppress_bleed,
)


@pytest.fixture
def workbench(qt_app, tmp_path):
    window = MainWindow(tmp_path / "data")
    sample = tmp_path / "sample.png"
    make_sample(sample)
    doc = window.store.add_document("Notes", str(sample), [sample, sample])
    window.load_page(window.store.pages(doc)[0].id)
    yield window
    if not window._closed:
        window.close()


def wait(app, condition):
    deadline = time.monotonic() + 20
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert condition()


def test_revision_sources_and_restore_are_persistent(workbench):
    w = workbench
    p = w.current_page.id
    w.replace_transcription("OCR original", "OCR")
    w.save_current()
    w.replace_transcription("Corrected wording", "dictionary")
    w.save_current()
    history = w.store.revisions(p)
    assert [r["source"] for r in history[:2]] == ["dictionary", "OCR"]
    w.replace_transcription(history[1]["text"], "restored revision")
    w.save_current()
    assert w.store.page(p).text == "OCR original"
    assert w.store.revisions(p)[0]["source"] == "restored revision"
    count = len(w.store.revisions(p))
    w.save_current()
    assert len(w.store.revisions(p)) == count


def test_fidelity_copies_remain_independent(workbench, monkeypatch):
    w = workbench
    w.replace_transcription("Faithful spelling", "manual")
    w.save_current()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("cleaned", True))
    w.fidelity()
    w.replace_transcription("Cleaned spelling", "writing rules")
    w.save_current()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("faithful", True))
    w.fidelity()
    assert w.editor.toPlainText() == "Faithful spelling"
    state = w.store.preference("fidelity:" + w.current_page.id)
    assert state["cleaned"] == "Cleaned spelling"


def test_searchable_pdf_preserves_images_and_manual_unicode(workbench, tmp_path):
    w = workbench
    w.replace_transcription("Manual café transcription survives export.", "manual")
    w.save_current()
    target = tmp_path / "searchable.pdf"
    export_document([w.store.page(w.current_page.id)], target, "Notes")
    with pymupdf.open(target) as pdf:
        assert len(pdf) == 1 and pdf[0].get_images()
        assert "transcription" in pdf[0].get_text()
        assert "café" in pdf[0].get_text()
        assert pdf[0].search_for("Manual")


def test_extended_rules_scope_exceptions_dates():
    rule = WritingRule(
        "x",
        "Colour",
        "replace",
        True,
        "color",
        "colour",
        scope="dialogue",
        exceptions="leave alone",
    )
    assert (
        preview_rules('color "color"\n"color leave alone"', [rule]).after
        == 'color "colour"\n"color leave alone"'
    )
    date = WritingRule("d", "ISO", "date_dmy_iso", True)
    assert preview_rules("24/10/2026 and 31/02/2026", [date]).after == "2026-10-24 and 31/02/2026"


def test_phrase_suggestions_and_real_engine_disagreements():
    d = Dictionary()
    proposals = phrase_suggestions("A note book and alot of words.", d)
    assert any(p.replacement == "notebook" for p in proposals)
    assert any(p.replacement == "a lot" for p in proposals)
    assert comparison("the name was Alice", "the name was Alison") == [
        ("replace", "Alice", "Alison")
    ]


def test_scan_tools_are_non_destructive_and_perspective_validated():
    image = Image.new("RGB", (300, 200), "white")
    draw = ImageDraw.Draw(image)
    for y in [40, 80, 120]:
        draw.rectangle((30, y, 260, y + 7), fill="black")
    before = image.tobytes()
    result, angle = deskew(image.rotate(4, fillcolor="white"))
    assert abs(angle + 4) <= 1 and result.width >= 300
    assert suppress_bleed(image).size == image.size
    assert perspective(image, [(0, 0), (299, 0), (299, 199), (0, 199)]).size == (299, 199)
    with pytest.raises(ValueError):
        perspective(image, [(0, 0)] * 4)
    assert image.tobytes() == before


def test_line_mode_writer_profiles_and_dialogs(workbench, qt_app):
    w = workbench
    page = w.store.page(w.current_page.id)
    dialog = LineDialog(
        page, {"boxes": [(0, 0, 100, 50), (0, 60, 100, 50)], "lines": ["first", "second"]}, w
    )
    dialog.text.setPlainText("corrected first")
    dialog.move(1)
    assert dialog.text.toPlainText() == "second"
    dialog.finish()
    assert dialog.lines == ["corrected first", "second"]
    w.store.set_preference(
        "writers",
        {
            "Alice": {
                "pack": "Medical",
                "words": ["Zorvax"],
                "abbreviations": {"pt": "patient"},
                "notes": "open r",
            }
        },
    )
    w.store.set_preference("active_writer", "Alice")
    w.reload_dictionary()
    assert w.dictionary.known("Zorvax") and w.dictionary.known("tachycardia")
    assert preview_rules("pt is stable", w.effective_rules()).after == "patient is stable"
    for obj in [
        ProfileDialog(w.store.preference("writers"), "Alice", w),
        PreferencesDialog(w),
        ReadingDialog(OcrResult("one", [], "a"), OcrResult("two", [], "b"), w),
    ]:
        obj.show()
        qt_app.processEvents()
        obj.close()


def test_persistent_queue_pause_resume_and_existing_text(workbench, qt_app, monkeypatch):
    w = workbench
    pages = w.store.pages(w.current_page.document_id)
    w.queue_document()
    assert len(w.store.queue_items()) == 2

    def recognize(*args):
        return OcrResult("Recognized page", [], "test")

    monkeypatch.setattr("document_transcriber.advanced_features.printed_ocr", recognize)
    w.start_queue()
    w.pause_queue()
    wait(qt_app, lambda: not w.busy)
    assert [j["status"] for j in w.store.queue_items()] == ["done", "queued"]
    w.start_queue()
    wait(qt_app, lambda: all(j["status"] == "done" for j in w.store.queue_items()))
    assert all(w.store.page(p.id).text == "Recognized page" for p in pages)


def test_queue_failure_retry_and_recovery(workbench, qt_app, monkeypatch):
    w = workbench
    w.error = lambda *args: None
    w.queue_document()

    def broken(*args):
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr("document_transcriber.advanced_features.printed_ocr", broken)
    w.start_queue()
    wait(qt_app, lambda: not w.busy)
    assert w.store.queue_items()[0]["status"] == "failed"
    assert w.queue_paused
    w.store.queue_update(w.store.queue_items()[0]["id"], "queued")
    monkeypatch.setattr(
        "document_transcriber.advanced_features.printed_ocr",
        lambda *a: OcrResult("retried", [], "test"),
    )
    w.start_queue()
    wait(qt_app, lambda: all(j["status"] == "done" for j in w.store.queue_items()))


def test_revision_batch_is_atomic_and_writer_corrections_are_scoped(workbench):
    w = workbench
    page = w.current_page.id
    with pytest.raises(KeyError):
        w.store.save_ocr_batch(
            [
                (page, OcrResult("should roll back", [], "test")),
                ("missing", OcrResult("bad", [], "test")),
            ]
        )
    assert w.store.page(page).text == "" and w.store.revisions(page) == []
    w.store.set_preference("active_writer", "Alice")
    w.learn_writer_correction("teh", "the")
    assert w.profile_corrections()["teh"] == "the"
    w.store.set_preference("active_writer", "Bob")
    assert "teh" not in w.profile_corrections()


def test_ordered_region_overlay_and_perspective_clicks(workbench, qt_app):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QGraphicsView

    from document_transcriber.advanced_ui import CornerDialog

    w = workbench
    w.show()
    w.viewer.region = QRectF(10, 20, 200, 40)
    w.add_reading_region()
    assert w.store.preference("regions:" + w.current_page.id) == [
        [10, 20, 200, 40]
    ] or w.store.preference("regions:" + w.current_page.id) == [(10, 20, 200, 40)]
    w.load_page(w.current_page.id)
    qt_app.processEvents()
    w.grab()
    dialog = CornerDialog(w.current_page.image_path, w)
    dialog.show()
    qt_app.processEvents()
    view = dialog.findChild(QGraphicsView)
    # Click four positions within the displayed scan, through the real event path.
    rect = view.mapFromScene(view.sceneRect()).boundingRect()
    for pos in [
        rect.topLeft() + QPoint(8, 8),
        rect.topRight() + QPoint(-8, 8),
        rect.bottomRight() + QPoint(-8, -8),
        rect.bottomLeft() + QPoint(8, -8),
    ]:
        QTest.mouseClick(
            view.viewport(), __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton, pos=pos
        )
    assert len(dialog.points) == 4
    dialog.close()


def test_queue_recovers_interrupted_jobs_without_starting_automatically(workbench):
    w = workbench
    root = w.data_dir
    w.queue_document()
    job = w.store.queue_items()[0]
    w.store.queue_update(job["id"], "running")
    w.close()
    reopened = MainWindow(root)
    assert all(j["status"] == "queued" for j in reopened.store.queue_items())
    assert reopened.queue_paused and not reopened.busy
    reopened.close()
