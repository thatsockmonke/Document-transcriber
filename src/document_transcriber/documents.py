from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence


class Cancelled(Exception):
    pass


def check_cancel(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled("Operation cancelled.")


@dataclass
class ImportedDocument:
    title: str
    source: str
    images: list[Path]


def import_files(
    paths: list[Path], staging: Path, cancel: threading.Event, progress=lambda message: None
) -> list[ImportedDocument]:
    staging.mkdir(parents=True, exist_ok=True)
    documents = []
    for file_number, path in enumerate(paths):
        check_cancel(cancel)
        progress(f"Importing {path.name}")
        images = []
        if path.suffix.lower() == ".pdf":
            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise ValueError(f"{path.name} is password-protected. Import an unlocked copy.")
                for index, page in enumerate(pdf):
                    check_cancel(cancel)
                    # Bound unusually large PDF pages without shrinking ordinary scans.
                    scale = min(1.7, 3200 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    target = staging / f"{file_number}-{index}.png"
                    pix.save(str(target))
                    images.append(target)
                    progress(f"{path.name} · page {index + 1} / {len(pdf)}")
        else:
            with Image.open(path) as image:
                for index, frame in enumerate(ImageSequence.Iterator(image)):
                    check_cancel(cancel)
                    frame = ImageOps.exif_transpose(frame).convert("RGB")
                    if max(frame.size) > 8000:
                        frame.thumbnail((8000, 8000), Image.Resampling.LANCZOS)
                    target = staging / f"{file_number}-{index}.png"
                    frame.save(target)
                    images.append(target)
        if not images:
            raise ValueError(f"{path.name} contains no readable pages.")
        documents.append(ImportedDocument(path.stem, str(path), images))
    return documents


def make_sample(path: Path):
    """A clearly identified printed sample for exercising local OCR."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 1550), "#fffdf8")
    draw = ImageDraw.Draw(image)
    font_paths = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    font_path = next((p for p in font_paths if p.exists()), None)

    def font(size):
        return (
            ImageFont.truetype(str(font_path), size)
            if font_path
            else ImageFont.load_default(size=size)
        )

    draw.text((95, 95), "FIELD NOTES", font=font(48), fill="#262626")
    draw.text((98, 164), "A PRINTED SAMPLE / DOCUMENT TRANSCRIBER", font=font(21), fill="#64605b")
    draw.line((95, 220, 1105, 220), fill="#b5b0a7", width=2)
    lines = [
        "A peace of cake is on the table.",
        "",
        "A notebook is a place to think slowly.",
        'She said "The notebook is ready."',
        "Leave enough space for a second thought.",
        "",
        "Project checklist",
        "1. Import the original document.",
        "2. Recognize text and review uncertain words.",
        "3. Add names to your personal dictionary.",
        "4. Export a clean, readable transcription.",
        "",
        "This sample uses printed text to test OCR.",
        "For handwriting, use the local TrOCR model",
        "and select a single line for best results.",
    ]
    y = 280
    for line in lines:
        draw.text((98, y), line, font=font(30), fill="#302e2a")
        y += 65
    draw.text(
        (98, 1440),
        "SAMPLE 01                                      LOCAL / PRIVATE / EDITABLE",
        font=font(18),
        fill="#7b766e",
    )
    image.save(path)


def export_document(pages, destination: Path, title: str):
    """Replace a destination only after its new export has been written successfully."""
    destination = Path(destination)
    handle, temporary = tempfile.mkstemp(
        prefix=".transcriber-", suffix=destination.suffix, dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary)
    try:
        _write_export(pages, temporary, title)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_export(pages, destination: Path, title: str):
    suffix = destination.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open() as output:
            for source in pages:
                with Image.open(source.image_path) as scan:
                    width, height = scan.size
                page = output.new_page(width=width * 0.6, height=height * 0.6)
                page.insert_image(page.rect, filename=str(source.image_path))
                # A separate invisible text flow preserves edited wording, including
                # manual text which no longer has valid OCR coordinates.
                font = pymupdf.Font("cjk")
                writer = pymupdf.TextWriter(page.rect)
                size = min(12, max(2, page.rect.width / 90))
                remaining = writer.fill_textbox(
                    page.rect + (8, 8, -8, -8), source.text, font=font, fontsize=size
                )
                if remaining:
                    writer = pymupdf.TextWriter(page.rect)
                    size = max(0.5, size * 0.5)
                    remaining = writer.fill_textbox(
                        page.rect + (8, 8, -8, -8), source.text, font=font, fontsize=size
                    )
                if remaining:
                    raise ValueError(
                        "Transcription is too long for a searchable layer on this page."
                    )
                writer.write_text(page, render_mode=3)
            output.set_metadata({"title": title})
            output.save(destination, garbage=4, deflate=True)
    elif suffix == ".json":
        destination.write_text(
            json.dumps(
                {
                    "format": "document-transcriber/1",
                    "title": title,
                    "pages": [
                        {
                            "number": p.number,
                            "text": p.text,
                            "notes": p.notes,
                            "reviewed": p.reviewed,
                            "engine": p.engine,
                            "tokens": p.tokens,
                        }
                        for p in pages
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    elif suffix == ".docx":
        from docx import Document

        document = Document()
        document.add_heading(title, 0)
        for index, page in enumerate(pages):
            if index:
                document.add_page_break()
            for paragraph in page.text.split("\n"):
                document.add_paragraph(paragraph)
        document.save(destination)
    elif suffix in {".txt", ".md"}:
        separator = "\n\n---\n\n" if suffix == ".md" else "\n\n\f\n\n"
        text = separator.join(page.text for page in pages)
        if suffix == ".md":
            text = f"# {title}\n\n{text}\n"
        destination.write_text(text, encoding="utf-8")
    else:
        raise ValueError("Choose .txt, .md, .docx, or .json for export.")
