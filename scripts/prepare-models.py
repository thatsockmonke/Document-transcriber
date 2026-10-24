#!/usr/bin/env python3
"""Download/verify the pinned handwriting model and optionally export an offline pack."""

import argparse
import threading
from pathlib import Path

from document_transcriber.models import export_pack, verify_model, write_manifest
from document_transcriber.ocr import download_handwriting_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--pack", type=Path, help="Write a portable model-pack ZIP")
    parser.add_argument(
        "--verify-only", action="store_true", help="Verify locally without network access"
    )
    args = parser.parse_args()
    cancel = threading.Event()
    if args.verify_only:
        verify_model(args.model_dir, cancel, print)
        write_manifest(args.model_dir)
    else:
        download_handwriting_model(args.model_dir, cancel, print)
    if args.pack:
        args.pack.parent.mkdir(parents=True, exist_ok=True)
        export_pack(args.model_dir, args.pack, cancel, print)
        print(f"Offline model pack: {args.pack}")


if __name__ == "__main__":
    main()
