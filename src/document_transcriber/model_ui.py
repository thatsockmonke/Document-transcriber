from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from .models import MODEL_ID, MODEL_REVISION, available
from .rule_ui import action, hint


class ModelLibraryDialog(QDialog):
    def __init__(self, model_dir, parent=None):
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.operation, self.path = None, None
        self.setWindowTitle("Local model library")
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel("LOCAL MODEL LIBRARY")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(
            hint(
                "Model packs let you move handwriting recognition to another computer without downloading the weights again. Documents always stay on your device."
            )
        )
        status = QLabel(
            "HANDWRITING  /  "
            + ("INSTALLED · VERIFIED ON LOAD" if available(model_dir) else "NOT INSTALLED")
        )
        status.setObjectName("orange")
        layout.addWidget(status)
        layout.addWidget(
            hint(
                f"{MODEL_ID}\n~247 MB on disk · CPU inference · English handwriting\nPinned revision {MODEL_REVISION[:12]}\nSingle-line crops give the best results."
            )
        )
        commands = QHBoxLayout()
        commands.addWidget(action("INSTALL MODEL PACK…", self.import_pack, True))
        commands.addWidget(action("DOWNLOAD MODEL", self.download))
        layout.addLayout(commands)
        export = action("EXPORT OFFLINE MODEL PACK…", self.export_pack)
        export.setEnabled(available(model_dir))
        layout.addWidget(export)
        layout.addWidget(
            hint(
                "The Python handwriting dependencies are separate from the model pack. Run scripts/install-handwriting.sh once on the destination computer."
            )
        )
        context = QLabel("DICTIONARY CONTEXT  /  BUNDLED")
        context.setObjectName("orange")
        layout.addWidget(context)
        layout.addWidget(
            hint(
                "An English n-gram model trained on 1.05 million words of public-domain prose is included in the application. Reviewed pages adapt suggestions to this project. It ranks likely wording; it does not guarantee meaning."
            )
        )
        location = hint(str(model_dir))
        location.setTextInteractionFlags(location.textInteractionFlags())
        layout.addWidget(location)
        layout.addStretch()
        layout.addWidget(action("DONE", self.reject))

    def download(self):
        self.operation = "download"
        self.accept()

    def import_pack(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Install verified model pack", "", "Model pack (*.zip)"
        )
        if path:
            self.operation, self.path = "import", Path(path)
            self.accept()

    def export_pack(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export model pack", "transcriber-handwriting-model.zip", "ZIP (*.zip)"
        )
        if path:
            self.operation, self.path = "export", Path(path)
            self.accept()
