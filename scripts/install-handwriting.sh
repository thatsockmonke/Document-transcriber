#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run ./scripts/setup.sh first.' >&2
  exit 1
fi
if command -v uv >/dev/null 2>&1; then
  if [[ -d /workspace && -w /workspace ]]; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.cache/uv}"
  fi
  uv sync --locked --extra dev --extra handwriting
else
  installer=(.venv/bin/python -m pip install)
  if [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]]; then
    "${installer[@]}" --index-url https://download.pytorch.org/whl/cpu 'torch>=2.6,<3'
  else
    "${installer[@]}" 'torch>=2.6,<3'
  fi
  "${installer[@]}" 'transformers>=4.53,<5' 'sentencepiece>=0.2,<1'
fi
.venv/bin/python -c 'import torch, transformers; print("Handwriting dependencies ready:", torch.__version__, transformers.__version__)'
echo 'Restart the app, then choose Tools → Download handwriting model.'

