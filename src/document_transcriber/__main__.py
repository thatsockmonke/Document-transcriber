import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Local document transcription workbench")
    parser.add_argument(
        "--data-dir", type=Path, help="Application data, settings, and model directory"
    )
    parser.add_argument(
        "--project", type=Path, help="Project directory (default: <data-dir>/workspace)"
    )
    parser.add_argument("--model-dir", type=Path, help="Verified local TrOCR small model directory")
    parser.add_argument(
        "--demo", action="store_true", help="Import the clearly labeled printed sample"
    )
    parser.add_argument("files", nargs="*", type=Path, help="Images or PDFs to import")
    args = parser.parse_args()
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    from .app import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Document Transcriber")
    app.setOrganizationName("DocumentTranscriber")
    root = (
        args.data_dir
        or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "document-transcriber"
    )
    try:
        window = MainWindow(root, args.project, args.model_dir)
    except Exception as error:
        print(f"Could not open Document Transcriber: {error}", file=sys.stderr)
        return 1
    window.show()
    if args.files:
        QTimer.singleShot(100, lambda: window.import_paths(args.files))
    elif args.demo:
        QTimer.singleShot(100, window.open_sample)
    status = app.exec()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return status


if __name__ == "__main__":
    sys.exit(main())
