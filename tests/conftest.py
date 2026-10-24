import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow
from shiboken6 import isValid


@pytest.fixture(scope="session")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def dispose_qt_windows(request):
    yield
    if "qt_app" not in request.fixturenames:
        return
    application = QApplication.instance()
    for widget in application.topLevelWidgets():
        # Completer popups are also top-level widgets, but are owned internally
        # by QCompleter. Deleting them separately would double-delete the view.
        if (
            isValid(widget)
            and isinstance(widget, (QMainWindow, QDialog))
            and widget.parent() is None
        ):
            if widget.isVisible():
                widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()
    # Collect Python-side signal cycles while QApplication is still alive.
    gc.collect()
