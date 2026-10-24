import json
import threading

import pymupdf
import pytest
from docx import Document
from PIL import Image, ImageDraw

from document_transcriber.dictionary import Dictionary, estimate, shift_tokens
from document_transcriber.documents import Cancelled, export_document, import_files, make_sample
from document_transcriber.ocr import line_regions, printed_ocr
from document_transcriber.storage import ProjectStore


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.png"
    make_sample(path)
    return path


def test_real_tesseract_recognition_and_region_coordinates(sample):
    result = printed_ocr(sample, None, threading.Event())
    assert "FIELD NOTES" in result.text
    assert "A notebook is a place to think slowly." in result.text
    assert len(result.tokens) > 60
    for token in result.tokens:
        assert result.text[token["start"] : token["end"]] == token["text"]
        assert 0 <= token["confidence"] <= 100
    region = printed_ocr(sample, (75, 75, 1000, 130), threading.Event())
    assert "FIELD NOTES" in region.text
    assert all(t["box"][0] >= 75 and t["box"][1] >= 75 for t in region.tokens)


def test_import_pdf_multipage_tiff_and_original_copy(tmp_path, sample):
    pdf_path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        for text in ["First original page", "Second original page"]:
            page = pdf.new_page()
            page.insert_text((72, 72), text)
        pdf.save(pdf_path)
    tiff_path = tmp_path / "multi.tiff"
    first, second = Image.new("RGB", (80, 100), "white"), Image.new("RGB", (90, 110), "gray")
    first.save(tiff_path, save_all=True, append_images=[second])
    documents = import_files([pdf_path, tiff_path, sample], tmp_path / "staging", threading.Event())
    assert [len(d.images) for d in documents] == [2, 2, 1]
    with Image.open(documents[1].images[1]) as image:
        assert image.size == (90, 110)
    store = ProjectStore(tmp_path / "project")
    identity = store.add_document("Notebook", str(sample), documents[2].images)
    page = store.pages(identity)[0]
    assert page.original_path.read_bytes() == sample.read_bytes()
    documents[2].images[0].unlink()
    assert page.original_path.is_file()
    store.close()


def test_project_persistence_dictionary_and_exports(tmp_path, sample):
    project = tmp_path / "project"
    store = ProjectStore(project)
    identity = store.add_document("Field notes", str(sample), [sample, sample])
    pages = store.pages(identity)
    tokens = [{"text": "Hello", "start": 0, "end": 5, "confidence": 71, "box": [1, 2, 30, 9]}]
    store.save_page(pages[0].id, "Hello, café 🦊", tokens, "Uncertain surname", True, "test engine")
    store.save_page(pages[1].id, "Second page", [], "", False, "")
    store.add_word("Crostini")
    store.learn_correction("teh", "the")
    store.close()
    store = ProjectStore(project)
    pages = store.pages(identity)
    assert pages[0].text == "Hello, café 🦊"
    assert pages[0].tokens == tokens
    assert pages[0].reviewed
    assert store.vocabulary() == ["crostini"]
    assert store.corrections() == {"teh": "the"}
    assert store.documents("café")[0]["id"] == identity
    for suffix in (".txt", ".md", ".docx", ".json"):
        path = tmp_path / f"export{suffix}"
        export_document(pages, path, "Field notes")
        assert path.stat().st_size > 0
    assert "Second page" in (tmp_path / "export.txt").read_text()
    assert (tmp_path / "export.md").read_text().startswith("# Field notes")
    assert "Hello, café 🦊" in [p.text for p in Document(tmp_path / "export.docx").paragraphs]
    payload = json.loads((tmp_path / "export.json").read_text())
    assert payload["pages"][0]["notes"] == "Uncertain surname"
    assert payload["pages"][0]["tokens"] == tokens
    originals = [p.original_path for p in pages]
    store.delete_document(identity)
    assert store.documents() == []
    assert all(not p.exists() for p in originals)
    assert sample.exists()
    store.close()


def test_dictionary_learned_corrections_and_word_completion():
    dictionary = Dictionary(["Crostini"], {"teh": "the"})
    assert dictionary.known("Crostini")
    assert not dictionary.known("transcripton")
    assert "transcription" in dictionary.suggestions("transcripton")
    assert "document" in dictionary.complete("docum")
    assert dictionary.correction("Teh") == "The"
    assert dictionary.correction("TEH") == "THE"
    assert dictionary.correction("unapproved") is None


def test_edit_alignment_never_reuses_changed_words():
    tokens = [{"text": "one", "start": 0, "end": 3}, {"text": "two", "start": 4, "end": 7}]
    shifted = shift_tokens(tokens, "one two", "🦊 one two")
    assert [(t["start"], t["end"]) for t in shifted] == [(2, 5), (6, 9)]
    changed = shift_tokens(tokens, "one two", "one three")
    assert [t["text"] for t in changed] == ["one"]
    assert tokens[1]["start"] == 4


def test_line_segmentation_and_cancel(sample, tmp_path):
    image = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 30, 500, 48), fill="black")
    draw.rectangle((60, 130, 480, 152), fill="black")
    assert len(line_regions(image)) == 2
    assert line_regions(Image.new("RGB", (500, 300), "white")) == []
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        import_files([sample], tmp_path / "staging", cancel)
    with pytest.raises(Cancelled):
        printed_ocr(sample, None, cancel)


def test_estimate_is_pace_based_and_reviewed_pages_are_complete():
    assert estimate("one two three four", False, 40, 120) == {
        "words": 4,
        "minutes": 0.1,
        "session_minutes": 2.0,
    }
    assert estimate("one two", True, 40, 0)["minutes"] == 0


def test_failed_export_preserves_existing_destination(tmp_path):
    path = tmp_path / "important.docx"
    path.write_bytes(b"original export")

    class BrokenPage:
        @property
        def text(self):
            raise RuntimeError("Simulate conversion failure")

    with pytest.raises(RuntimeError):
        export_document([BrokenPage()], path, "Notes")
    assert path.read_bytes() == b"original export"
    assert list(tmp_path.glob(".transcriber-*")) == []
