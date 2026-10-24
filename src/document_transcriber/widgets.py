from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCompleter,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QPlainTextEdit,
    QWidget,
)

from .dictionary import WORD_RE
from .documents import Cancelled


class JobSignals(QObject):
    progress = Signal(str)
    done = Signal(object, str, bool)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.function(self.cancel, self.signals.progress.emit)
            self.signals.done.emit(result, "", self.cancel.is_set())
        except Cancelled:
            self.signals.done.emit(None, "", True)
        except Exception as error:
            self.signals.done.emit(None, f"{type(error).__name__}: {error}", False)


class ImageViewer(QGraphicsView):
    regionChanged = Signal(object)
    wordClicked = Signal(int)
    zoomChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#0d1012"))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.item = None
        self.selection_mode = False
        self.region = None
        self._anchor = None
        self.tokens = []
        self.ordered_regions = []
        self.active_box = None
        self._fit = True

    def load(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError(f"Cannot display image: {path}")
        self.scene().clear()
        self.item = QGraphicsPixmapItem(pixmap)
        self.scene().addItem(self.item)
        self.scene().setSceneRect(self.item.boundingRect().adjusted(-35, -35, 35, 35))
        self.tokens = []
        self.active_box = None
        self.region = None
        self.regionChanged.emit(None)
        self.fit_page()

    def clear(self):
        self.scene().clear()
        self.item = None
        self.tokens = []
        self.active_box = None
        self.region = None
        self.regionChanged.emit(None)

    def fit_page(self):
        self._fit = True
        if self.item:
            self.fitInView(self.item.boundingRect().adjusted(-25, -25, 25, 25), Qt.KeepAspectRatio)
            self.zoomChanged.emit(round(self.transform().m11() * 100))

    def zoom(self, factor):
        if self.item and 0.04 < self.transform().m11() * factor < 8:
            self._fit = False
            self.scale(factor, factor)
            self.zoomChanged.emit(round(self.transform().m11() * 100))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.fit_page()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def select_mode(self, checked):
        self.selection_mode = checked
        self.setDragMode(QGraphicsView.NoDrag if checked else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if checked else Qt.OpenHandCursor)

    def clear_region(self):
        self.region = None
        self.regionChanged.emit(None)
        self.viewport().update()

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self.selection_mode and self.item and event.button() == Qt.LeftButton:
            if self.item.boundingRect().contains(point):
                self._anchor = point
                self.region = QRectF(point, point)
                event.accept()
                return
        if event.button() == Qt.LeftButton:
            for index, token in enumerate(self.tokens):
                if QRectF(*token["box"]).contains(point):
                    self.wordClicked.emit(index)
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._anchor is not None:
            point = self.mapToScene(event.position().toPoint())
            self.region = (
                QRectF(self._anchor, point).normalized().intersected(self.item.boundingRect())
            )
            self.viewport().update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._anchor is not None:
            self._anchor = None
            if self.region.width() < 8 or self.region.height() < 8:
                self.region = None
            self.regionChanged.emit(self.region_tuple())
            self.viewport().update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def region_tuple(self):
        if self.region is None:
            return None
        return tuple(
            round(v)
            for v in (self.region.x(), self.region.y(), self.region.width(), self.region.height())
        )

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.item:
            pen = QPen(QColor("#ff9147"))
            pen.setCosmetic(True)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            font = painter.font()
            font.setPixelSize(max(12, round(13 / max(0.05, self.transform().m11()))))
            painter.setFont(font)
            for number, box in enumerate(self.ordered_regions, 1):
                painter.drawRect(QRectF(*box))
                painter.drawText(
                    QRectF(box[0], box[1], box[2], 40 / max(0.05, self.transform().m11())),
                    str(number),
                )
        if self.item is None:
            painter.save()
            painter.resetTransform()
            width, height = self.viewport().width(), self.viewport().height()
            center_x, center_y = width // 2, height // 2 - 40
            painter.fillRect(QRect(center_x - 34, center_y - 68, 68, 68), QColor("#27221c"))
            painter.setPen(QPen(QColor("#f28b42"), 2))
            painter.drawRect(center_x - 18, center_y - 54, 36, 40)
            for y, length in ((-44, 23), (-36, 23), (-28, 14)):
                painter.drawLine(center_x - 11, center_y + y, center_x - 11 + length, center_y + y)
            painter.setFont(QFont("DejaVu Sans", 10, QFont.Bold))
            painter.setPen(QColor("#b8bfc4"))
            painter.drawText(
                QRect(0, center_y + 24, width, 24), Qt.AlignCenter, "DROP A DOCUMENT HERE"
            )
            painter.setFont(QFont("DejaVu Sans", 9))
            painter.setPen(QColor("#66737d"))
            painter.drawText(
                QRect(0, center_y + 55, width, 24), Qt.AlignCenter, "PDF  /  PNG  /  JPEG  /  TIFF"
            )
            painter.restore()
            return
        pen = QPen(QColor("#e88440"), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for token in self.tokens:
            confidence = token.get("confidence")
            if confidence is not None and confidence < 75:
                painter.fillRect(QRectF(*token["box"]), QColor(241, 139, 66, 35))
                painter.drawRect(QRectF(*token["box"]))
        if self.active_box:
            painter.fillRect(QRectF(*self.active_box), QColor(241, 139, 66, 75))
            painter.drawRect(QRectF(*self.active_box))
        if self.region:
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.fillRect(self.region, QColor(241, 139, 66, 35))
            painter.drawRect(self.region)


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_numbers(event)


class TranscriptionEditor(QPlainTextEdit):
    corrected = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.dictionary = None
        self.auto_correct = False
        self.setFont(QFont("DejaVu Sans Mono", 12))
        self.setPlaceholderText(
            "Your transcription starts here.\n\nRun OCR, or type while reading the original.\n\nCtrl+Space  →  word completion\nCtrl+F      →  find and replace"
        )
        self.setTabStopDistance(32)
        self.gutter = LineNumbers(self)
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self.scroll_gutter)
        self.update_gutter()
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)

    def gutter_width(self):
        return 18 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def update_gutter(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def scroll_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_gutter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def paint_numbers(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor("#121517"))
        painter.setFont(QFont("DejaVu Sans Mono", 9))
        painter.setPen(QColor("#53606a"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self.gutter.width() - 9,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(block.blockNumber() + 1).zfill(2),
                )
            top += height
            block = block.next()

    def insert_completion(self, word):
        cursor = self.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        cursor.insertText(word)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if self.completer.popup().isVisible() and event.key() in (
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_Escape,
            Qt.Key_Tab,
            Qt.Key_Backtab,
        ):
            event.ignore()
            return
        if event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
            cursor = self.textCursor()
            cursor.select(QTextCursor.WordUnderCursor)
            words = self.dictionary.complete(cursor.selectedText()) if self.dictionary else []
            if words:
                self.completer.setModel(QStringListModel(words, self.completer))
                self.completer.setCompletionPrefix("")
                self.completer.complete(self.cursorRect())
            return
        if (
            self.auto_correct
            and self.dictionary
            and not self.textCursor().hasSelection()
            and event.text() in (" ", ".", ",", "!", "?", ":", ";", "\r", "\n")
        ):
            cursor = self.textCursor()
            # Corrections only apply when typing at the end of a word.
            text = self.toPlainText()
            position = len(
                text.encode("utf-16-le")[: cursor.position() * 2].decode(
                    "utf-16-le", errors="ignore"
                )
            )
            if position and (position == len(text) or not text[position].isalpha()):
                cursor.select(QTextCursor.WordUnderCursor)
                original = cursor.selectedText()
                replacement = self.dictionary.correction(original)
                if replacement and replacement != original:
                    cursor.beginEditBlock()
                    cursor.insertText(replacement)
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    self.corrected.emit(original, replacement)
        super().keyPressEvent(event)


class SpellingHighlighter(QSyntaxHighlighter):
    def __init__(self, document, dictionary):
        super().__init__(document)
        self.dictionary = dictionary
        self.enabled = True
        self.spelling = QTextCharFormat()
        self.spelling.setUnderlineColor(QColor("#d78a5e"))
        self.spelling.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)

    def highlightBlock(self, text):
        if self.enabled:
            for match in WORD_RE.finditer(text):
                if not self.dictionary.known(match.group()):
                    start = len(text[: match.start()].encode("utf-16-le")) // 2
                    length = len(match.group().encode("utf-16-le")) // 2
                    self.setFormat(start, length, self.spelling)
