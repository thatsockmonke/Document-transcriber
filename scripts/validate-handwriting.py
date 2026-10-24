#!/usr/bin/env python3
"""Validate a local handwriting model on a supplied line image, without networking."""

import argparse
import json
import os
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--reference", required=True, help="Ground-truth text for this single line")
    parser.add_argument(
        "--max-cer", type=float, default=0.3, help="Maximum character edit rate for this smoke test"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    from PIL import Image
    from rapidfuzz.distance import Levenshtein

    from document_transcriber.ocr import handwritten_ocr

    with Image.open(args.image) as image:
        width, height = image.size
    start = time.monotonic()
    result = handwritten_ocr(
        args.image, (0, 0, width, height), args.model_dir, threading.Event(), print
    )
    edits = Levenshtein.distance(args.reference, result.text)
    report = {
        "reference": args.reference,
        "recognized": result.text,
        "character_edit_rate": edits / max(1, len(args.reference)),
        "seconds": round(time.monotonic() - start, 2),
        "offline": True,
    }
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not result.text or report["character_edit_rate"] > args.max_cer:
        raise SystemExit("This line did not meet the requested smoke-test threshold.")


if __name__ == "__main__":
    main()
