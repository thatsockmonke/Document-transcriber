#!/usr/bin/env python3
"""Package the app wheel, verified handwriting pack, and Crostini launch helpers."""

import argparse
import json
import tempfile
import threading
import zipfile
from pathlib import Path

from document_transcriber import __version__
from document_transcriber.models import MODEL_NAME, install_pack, manifest, sha256

INSTALL = r"""#!/usr/bin/env bash
set -euo pipefail
transcriber_bundle_root="$(cd "$(dirname "$0")" && pwd)"
cd "$transcriber_bundle_root"
python3 -m venv .venv
export PIP_CACHE_DIR="$transcriber_bundle_root/.cache/pip"
if [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]]; then
  .venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch>=2.6,<3'
fi
.venv/bin/python -m pip install './APP_WHEEL[handwriting]'
.venv/bin/python - <<'PY'
from pathlib import Path
import threading
from document_transcriber.models import MODEL_NAME, install_pack
install_pack(Path('transcriber-handwriting-model.zip'), Path('models') / MODEL_NAME,
             threading.Event(), print)
print('Verified model installed locally. Run: bash run.sh')
PY
"""

RUN = r"""#!/usr/bin/env bash
set -euo pipefail
transcriber_bundle_root="$(cd "$(dirname "$0")" && pwd)"
exec "$transcriber_bundle_root/.venv/bin/document-transcriber" \
  --model-dir "$transcriber_bundle_root/models/trocr-small-handwritten" "$@"
"""

README = """Document Transcriber {version} — application + local models

For Linux / ChromeOS Crostini, Python 3.10+.

1. Enable ChromeOS's Linux development environment and open Linux Terminal.
2. Install system prerequisites:
   sudo apt update
   sudo apt install python3-venv tesseract-ocr tesseract-ocr-eng libegl1 libopengl0 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 fonts-dejavu-core
3. Extract this archive to a writable Linux folder, then run:
   bash install.sh
4. Start the application:
   bash run.sh

Fedora KDE / Wayland prerequisites instead of apt:
   sudo dnf install python3 python3-pip tesseract tesseract-langpack-eng qt6-qtwayland
   QT_QPA_PLATFORM=wayland bash run.sh

Optional desktop launcher, after installation:
   python3 scripts/install-desktop.py

The installer needs Internet access to install Python dependencies. This archive
contains the application, bundled English context model, and the handwriting
weights/tokenizer pack; it is not a full offline operating-system/Python installer.
After dependencies are installed, handwriting, spelling suggestions, writing rules,
and project editing work locally. No document content is sent to an external service.

The installer uses CPU PyTorch on x86 Linux. ARM package availability depends on
Python and Chromebook hardware. Actual Chromebook hardware was not tested.

The Models screen can import/export the model pack independently. All model files
are verified against the application's pinned checksums before loading. Source
model cards and original notices are included. Review handwriting output; proper
names and difficult scans can still be misread. Context ranking is statistical,
not a guarantee of meaning.

The app stores project data in ~/.local/share/document-transcriber by default
(or under XDG_DATA_HOME if set). Use --data-dir and --project to choose locations.
Back up projects from File > Back up project before moving or deleting their folder.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--model-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.wheel.is_file() or not args.model_pack.is_file():
        raise ValueError("Both the app wheel and verified model pack are required.")
    if args.wheel.name != f"document_transcriber-{__version__}-py3-none-any.whl":
        raise ValueError("Wheel version does not match the application.")
    with zipfile.ZipFile(args.model_pack) as pack:
        if json.loads(pack.read("manifest.json")) != manifest():
            raise ValueError("Unexpected handwriting-model provenance.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".verify-release-", dir=args.output.parent
    ) as directory:
        install_pack(args.model_pack, Path(directory) / MODEL_NAME, threading.Event())
    with tempfile.NamedTemporaryFile(
        prefix=".release-", suffix=".zip", dir=args.output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as archive:
            archive.write(args.wheel, args.wheel.name)
            archive.write(args.model_pack, "transcriber-handwriting-model.zip")
            archive.write(
                Path(__file__).with_name("install-desktop.py"), "scripts/install-desktop.py"
            )
            for name, content in {
                "install.sh": INSTALL.replace("APP_WHEEL", args.wheel.name),
                "run.sh": RUN,
                "START-HERE.txt": README.format(version=__version__),
                "SHA256SUMS": f"{sha256(args.wheel)}  {args.wheel.name}\n{sha256(args.model_pack)}  transcriber-handwriting-model.zip\n",
            }.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
                archive.writestr(info, content)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Created application + models bundle: {args.output}")


if __name__ == "__main__":
    main()
