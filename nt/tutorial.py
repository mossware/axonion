from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont


class TutorialOverlay(QWidget):
    def __init__(self, parent, steps):
        super().__init__(parent)

        self.parent = parent
        self.steps = steps
        self.index = 0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()

    # navigation

    def mousePressEvent(self, event):
        self.index += 1
        if self.index >= len(self.steps):
            self.close()
        else:
            self.update()

    # geometry

    def target_rect(self):
        widget, _ = self.steps[self.index]

        if widget is None or not widget.isVisible():
            return None

        rect = widget.geometry()
        w = widget.parentWidget()
        while w and w != self.parent:
            rect.moveTopLeft(w.mapToParent(rect.topLeft()))
            w = w.parentWidget()

        pad = 10
        rect = rect.adjusted(-pad, -pad, pad, pad)

        if rect.height() < 40:
            rect = rect.adjusted(-6, -10, 6, 10)

        return rect

    # paint

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        target = self.target_rect()

        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

        if target:
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(target, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            painter.setPen(QPen(QColor("#9fffba"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(target, 8, 8)

        box = QRect(
            40,
            self.height() - 180,
            min(440, self.width() - 80),
            140
        )

        painter.setPen(QPen(QColor("#1a1f22"), 1))
        painter.setBrush(QColor("#0c0e10"))
        painter.drawRoundedRect(box, 12, 12)

        painter.setPen(QColor("#d7e1d9"))
        painter.setFont(QFont("Sans Serif", 10))

        _, text = self.steps[self.index]
        painter.drawText(
            box.adjusted(16, 14, -16, -14),
            Qt.TextWordWrap,
            text + "\n\n(click to continue)"
        )
