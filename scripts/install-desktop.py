#!/usr/bin/env python3
"""Install a user-local desktop launcher for Linux, KDE Wayland, and Crostini."""

import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
executable = root / ".venv/bin/document-transcriber"
if not executable.exists():
    raise SystemExit("Install the application into .venv first.")
if (root / "run.sh").exists():
    executable = root / "run.sh"
target = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
target.mkdir(parents=True, exist_ok=True)
path = (
    str(executable)
    .replace("\\", "\\\\")
    .replace('"', '\\"')
    .replace("`", "\\`")
    .replace("$", "\\$")
)
(target / "document-transcriber.desktop").write_text(
    '[Desktop Entry]\nType=Application\nName=Document Transcriber\nComment=Local handwriting transcription workbench\nExec="'
    + path
    + '" %F\nTerminal=false\nCategories=Office;Utility;\nMimeType=application/pdf;image/png;image/jpeg;image/tiff;\nStartupNotify=true\n',
    encoding="utf-8",
)
print("Installed launcher:", target / "document-transcriber.desktop")
