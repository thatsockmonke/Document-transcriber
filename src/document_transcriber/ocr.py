"""Actual local OCR backends, with explicit model installation and cancellation."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .documents import check_cancel
from .models import download_model, verify_model


def _configure_model_cache(model_dir: Path):
    # Keep downloads writable even in cloud machines with a read-only home directory.
    cache = model_dir.parent / "huggingface-cache"
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HF_XET_CACHE", str(cache / "xet"))


@dataclass
class OcrResult:
    text: str
    tokens: list[dict]
    engine: str


def printed_ocr(
    image_path: Path, region: tuple | None, cancel: threading.Event, progress=lambda message: None
) -> OcrResult:
    import pytesseract

    check_cancel(cancel)
    progress("Recognizing with local Tesseract…")
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    offset_x, offset_y = 0, 0
    if region:
        offset_x, offset_y, width, height = region
        image = image.crop((offset_x, offset_y, offset_x + width, offset_y + height))
    data = pytesseract.image_to_data(
        image,
        config="--psm 6" if region else "--psm 3",
        output_type=pytesseract.Output.DICT,
        timeout=120,
    )
    check_cancel(cancel)
    text = ""
    tokens = []
    previous_line = None
    previous_paragraph = None
    for index, raw in enumerate(data["text"]):
        word = raw.strip()
        if not word or float(data["conf"][index]) < 0:
            continue
        line = tuple(data[k][index] for k in ("block_num", "par_num", "line_num"))
        paragraph = line[:2]
        if text:
            text += (
                ("\n\n" if paragraph != previous_paragraph else "\n")
                if line != previous_line
                else " "
            )
        start = len(text)
        text += word
        tokens.append(
            {
                "text": word,
                "start": start,
                "end": len(text),
                "confidence": round(float(data["conf"][index]), 1),
                "box": [
                    int(data["left"][index]) + offset_x,
                    int(data["top"][index]) + offset_y,
                    int(data["width"][index]),
                    int(data["height"][index]),
                ],
            }
        )
        previous_line, previous_paragraph = line, paragraph
    return OcrResult(text, tokens, "Tesseract / printed")


def download_handwriting_model(
    model_dir: Path, cancel: threading.Event, progress=lambda message: None
):
    _configure_model_cache(model_dir)
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "Install handwriting dependencies first. In the project folder run:\n"
            "./scripts/install-handwriting.sh\nThen restart the app."
        ) from error
    check_cancel(cancel)
    download_model(model_dir, cancel, progress)
    check_cancel(cancel)
    progress("Verifying model can load locally…")
    _load_model(model_dir)
    return model_dir


_loaded_model = None
_loaded_path = None


def _load_model(model_dir):
    global _loaded_model, _loaded_path
    if _loaded_model is not None and _loaded_path == str(model_dir):
        return _loaded_model
    _configure_model_cache(model_dir)
    try:
        import torch
        from transformers import AutoImageProcessor, AutoTokenizer, VisionEncoderDecoderModel
    except ImportError as error:
        raise RuntimeError(
            "Handwriting dependencies are missing. Run ./scripts/install-handwriting.sh, "
            "restart the app, then download the model from Tools."
        ) from error
    if not (model_dir / "config.json").exists():
        raise RuntimeError(
            "Open Models to install an offline model pack or download the handwriting model. "
            "After installation, recognition works offline."
        )
    verify_model(model_dir)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    processor = AutoImageProcessor.from_pretrained(
        str(model_dir), local_files_only=True, use_fast=False, trust_remote_code=False
    )
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, use_fast=False)
    model = VisionEncoderDecoderModel.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    )
    model.eval()
    _loaded_model = processor, tokenizer, model
    _loaded_path = str(model_dir)
    return _loaded_model


def line_regions(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Projection-based line segmentation; manual single-line regions are preferable."""
    import numpy as np

    gray = np.asarray(ImageOps.autocontrast(image.convert("L")))
    ink = gray < 160
    # Ignore the outer 1%, where scan borders tend to introduce false lines.
    margin = max(1, image.width // 100)
    ink[:, :margin] = False
    ink[:, -margin:] = False
    rows = ink.sum(axis=1) > max(2, image.width * 0.002)
    runs = []
    start = None
    last = 0
    gap = max(3, image.height // 250)
    for y, active in enumerate(rows):
        if active:
            if start is None:
                start = y
            last = y
        elif start is not None and y - last > gap:
            if last - start >= 5:
                runs.append((start, last + 1))
            start = None
    if start is not None and last - start >= 5:
        runs.append((start, last + 1))
    boxes = []
    for top, bottom in runs:
        columns = np.flatnonzero(ink[top:bottom].sum(axis=0))
        if columns.size:
            left, right = max(0, int(columns[0]) - 8), min(image.width, int(columns[-1]) + 9)
            top, bottom = max(0, top - 8), min(image.height, bottom + 8)
            boxes.append((left, top, right - left, bottom - top))
    return boxes


def handwritten_ocr(
    image_path: Path,
    region: tuple | None,
    model_dir: Path,
    cancel: threading.Event,
    progress=lambda message: None,
) -> OcrResult:
    check_cancel(cancel)
    progress("Loading the local handwriting model…")
    processor, tokenizer, model = _load_model(model_dir)
    import torch

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    boxes = [region] if region else line_regions(image)
    if not boxes:
        return OcrResult("", [], "TrOCR / handwriting")
    lines = []
    tokens = []
    offset = 0
    for index, (x, y, width, height) in enumerate(boxes):
        check_cancel(cancel)
        progress(f"Recognizing handwritten line {index + 1} / {len(boxes)}…")
        crop = image.crop((x, y, x + width, y + height))
        pixels = processor(images=crop, return_tensors="pt").pixel_values
        with torch.inference_mode():
            ids = model.generate(pixels, max_new_tokens=128, num_beams=3)
        text = tokenizer.batch_decode(ids, skip_special_tokens=True)[0].strip()
        if text:
            if lines:
                offset += 1
            # TrOCR has no calibrated word confidence or word boxes. Keep line alignment.
            tokens.append(
                {
                    "text": text,
                    "start": offset,
                    "end": offset + len(text),
                    "confidence": None,
                    "box": [x, y, width, height],
                }
            )
            lines.append(text)
            offset += len(text)
    check_cancel(cancel)
    return OcrResult("\n".join(lines), tokens, "TrOCR / handwriting")
