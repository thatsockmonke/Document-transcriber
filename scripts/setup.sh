#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  if [[ -d /workspace && -w /workspace ]]; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.cache/uv}"
  fi
  uv sync --locked --extra dev --inexact
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[dev]'
fi
.venv/bin/python -c 'from PySide6.QtWidgets import QApplication; import pymupdf, pytesseract, spellchecker'
if ! command -v tesseract >/dev/null 2>&1; then
  echo 'Printed OCR requires: sudo apt install tesseract-ocr tesseract-ocr-eng' >&2
  exit 1
fi
tesseract --version

