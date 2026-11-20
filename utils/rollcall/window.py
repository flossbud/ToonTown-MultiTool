"""The frameless window the installer, the update window and the uninstaller
live in: a stage with real rounded corners and a soft shadow, on a
translucent top-level.

The shadow needs room around the stage, so the top-level is larger than the
stage by ``margin`` on every side (plus the shadow's 24 px drop below). The
empty part is fully transparent and does not take clicks.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtWidgets import QGraphicsEffect, QWidget

from utils.rollcall import paint
from utils.rollcall import tokens as T
from utils.rollcall.fonts import asset_path
from utils.rollcall.stage import Stage

SHADOW_BLUR = 60
SHADOW_DROP = 24
SHADOW_ALPHA = 0.55


class Saturation(QGraphicsEffect):
    """Drains colour from everything under it: ``amount`` 1 is full colour,
    0 is grey. The uninstaller turns the whole stage down as it empties."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._amount = 1.0

    def amount(self) -> float:
        return self._amount

    def set_amount(self, amount: float) -> None:
        amount = max(0.0, min(1.0, float(amount)))
        if abs(amount - self._amount) > 0.002:
            self._amount = amount
            self.update()

    def draw(self, painter: QPainter) -> None:
        if self._amount >= 0.999:
            self.drawSource(painter)
            return
        result = self.sourcePixmap(Qt.LogicalCoordinates)
        pixmap, offset = result if isinstance(result, tuple) else (result, QPoint())
        if pixmap.isNull():
            return
        ratio = pixmap.devicePixelRatio()
        colour = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        grey = colour.convertToFormat(QImage.Format_Grayscale8).convertToFormat(
            QImage.Format_ARGB32_Premultiplied)
        colour.setDevicePixelRatio(1.0)
        grey.setDevicePixelRatio(1.0)
        mask = QPainter(grey)
        mask.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask.drawImage(0, 0, colour)
        mask.end()
        colour.setDevicePixelRatio(ratio)
        grey.setDevicePixelRatio(ratio)
        painter.save()
        painter.drawImage(offset, colour)
        painter.setOpacity(1.0 - self._amount)
        painter.drawImage(offset, grey)
        painter.restore()


class RollcallWindow(QWidget):
    """A stage in its own window. Subclasses are the three surfaces; they
    override ``request_close`` to decide what the close button means."""

    def __init__(self, variant: T.Variant, title: str):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint
                         | Qt.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowTitle(title)
        icon = asset_path("ToonTownMultiTool.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.variant = variant
        self._margin = int(SHADOW_BLUR * 1.25)
        self.stage = Stage(variant, self)
        self.stage.move(self._margin, self._margin)
        self.setFixedSize(variant.width + 2 * self._margin,
                          variant.height + 2 * self._margin + SHADOW_DROP)
        self.stage.background_pressed.connect(self._on_stage_pressed)
        if self.stage.lights is not None:
            self.stage.lights.minimize_clicked.connect(self.showMinimized)
            self.stage.lights.close_clicked.connect(self._on_close_clicked)
        self._saturation: Saturation | None = None
        self._allow_close = False

    # ── Close ──────────────────────────────────────────────────────────────

    def request_close(self) -> bool:
        """The player asked to close (the red light, Alt+F4, Esc). Return
        True to let the window go; False if the surface handled it."""
        return True

    def _on_close_clicked(self) -> None:
        if self.request_close():
            self.close_now()

    def close_now(self) -> None:
        self._allow_close = True
        self.close()

    def closeEvent(self, event) -> None:
        if self._allow_close or self.request_close():
            # A closed window paints nothing: let its clocks stop.
            self.stage._ticker.stop()
            self.stage.copy._ticker.stop()
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._on_close_clicked()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            for control in self.stage.copy.controls():
                if getattr(control, "kind", "") == "gold" and control.isEnabled():
                    control.click()
                    return
        super().keyPressEvent(event)

    # ── Looks ──────────────────────────────────────────────────────────────

    def set_saturation(self, amount: float) -> None:
        if self._saturation is None:
            if amount >= 0.999:
                return
            self._saturation = Saturation(self.stage)
            self.stage.setGraphicsEffect(self._saturation)
        self._saturation.set_amount(amount)

    def saturation(self) -> float:
        return 1.0 if self._saturation is None else self._saturation.amount()

    def centre_on_screen(self, screen=None) -> None:
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.x() + (area.width() - self.variant.width) // 2 - self._margin
        y = area.y() + (area.height() - self.variant.height) // 2 - self._margin
        self.move(x, y)

    def _on_stage_pressed(self, event) -> None:
        if event.button() == Qt.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    def paintEvent(self, _event) -> None:
        v = self.variant
        p = QPainter(self)
        shadow, margin = paint.box_shadow(v.width, v.height, v.radius, SHADOW_BLUR,
                                          SHADOW_ALPHA, self.devicePixelRatioF())
        p.drawPixmap(QPoint(self._margin - margin, self._margin - margin + SHADOW_DROP), shadow)
        p.end()

    def grab_stage(self) -> QImage:
        """The window as the player sees it, shadow included (shots, tests)."""
        return self.grab().toImage()


def later(ms: int, callback) -> QTimer:
    """A single-shot timer the caller can keep and cancel."""
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(ms)
    return timer


def stage_rect_in_window(window: RollcallWindow) -> QRectF:
    return QRectF(window.stage.geometry())
