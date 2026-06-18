"""In-app 'takes over' color picker. Contained in the app window; never QColorDialog."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from utils.widgets.toon_customization_sections import PRESET_SWATCHES

_PRESETS = list(PRESET_SWATCHES[:5])


class _SatBrightSquare(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 160)
        self._h = 0.6
        self._s = 1.0
        self._v = 1.0

    def set_hsv(self, h, s, v):
        self._h, self._s, self._v = h, s, v
        self.update()

    def hsv(self):
        return self._h, self._s, self._v

    def paintEvent(self, _):
        p = QPainter(self)
        w, hgt = self.width(), self.height()
        base = QColor.fromHsvF(self._h, 1.0, 1.0)
        gx = QLinearGradient(0, 0, w, 0)
        gx.setColorAt(0, QColor("#ffffff"))
        gx.setColorAt(1, base)
        p.fillRect(self.rect(), gx)
        gy = QLinearGradient(0, 0, 0, hgt)
        gy.setColorAt(0, QColor(0, 0, 0, 0))
        gy.setColorAt(1, QColor("#000000"))
        p.fillRect(self.rect(), gy)
        cx = int(self._s * w)
        cy = int((1 - self._v) * hgt)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QPoint(cx, cy), 6, 6)

    def mousePressEvent(self, e):
        self._pick(e)

    def mouseMoveEvent(self, e):
        self._pick(e)

    def _pick(self, e):
        self._s = min(1.0, max(0.0, e.position().x() / self.width()))
        self._v = min(1.0, max(0.0, 1 - e.position().y() / self.height()))
        self.update()
        self.changed.emit()


class ColorPickerOverlay(QWidget):
    color_live = Signal(str)
    color_committed = Signal(object)   # hex str or None (Auto)
    cancelled = Signal()

    def __init__(self, parent: QWidget, *, saved_store):
        super().__init__(parent)
        self._store = saved_store
        self.setObjectName("ColorPickerOverlay")
        self._build()
        self.hide()

    # ── public API ──────────────────────────────────────────────────────────

    def open_for(self, start_hex: Optional[str]) -> None:
        """Show the picker initialised to start_hex (or #4a7cff if None/invalid).

        Does NOT emit color_live on open.
        """
        hex_ = start_hex or "#4a7cff"
        c = QColor(hex_)
        if not c.isValid():
            c = QColor("#4a7cff")
        h, s, v, _ = c.getHsvF()
        if h < 0:
            h = 0.0
        self._square.set_hsv(h, s, v)
        self._hue.blockSignals(True)
        self._hue.setValue(int(round(h * 359)))
        self._hue.blockSignals(False)
        self._hex.setText(c.name())
        self._rebuild_saved()
        if self.parent() is not None:
            self.resize(self.parent().size())
        self.raise_()
        self.show()

    def set_hex(self, hex_: str) -> None:
        """Validate, normalise, update all controls and emit color_live."""
        c = QColor(hex_)
        if not c.isValid():
            return
        normalized = c.name()   # lowercase #rrggbb
        h, s, v, _ = c.getHsvF()
        if h < 0:
            h = 0.0
        self._square.set_hsv(h, s, v)
        self._hue.blockSignals(True)
        self._hue.setValue(int(round(h * 359)))
        self._hue.blockSignals(False)
        self._hex.setText(normalized)
        self.color_live.emit(normalized)

    def current_hex(self) -> str:
        """Return the current hex string (lowercase #rrggbb)."""
        return self._hex.text()

    def commit(self):
        self.hide()
        self.color_committed.emit(self.current_hex())

    def choose_auto(self):
        self.hide()
        self.color_committed.emit(None)

    def cancel(self):
        self.hide()
        self.cancelled.emit()

    def save_current(self):
        self._store.save(self.current_hex())
        self._rebuild_saved()

    # ── private ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Card frame - centered child, drawn on top of the scrim
        self._card = QFrame(self)
        self._card.setObjectName("pickerCard")
        self._card.setStyleSheet(
            "QFrame#pickerCard {"
            "  background: #1f2230;"
            "  border: 1px solid #3a3f55;"
            "  border-radius: 10px;"
            "}"
        )
        self._card.setFixedWidth(268)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        # Sat/bright square
        self._square = _SatBrightSquare(self._card)
        self._square.changed.connect(self._on_square_changed)
        card_layout.addWidget(self._square, 0, Qt.AlignmentFlag.AlignHCenter)

        # Hue slider
        self._hue = QSlider(Qt.Orientation.Horizontal, self._card)
        self._hue.setRange(0, 359)
        self._hue.setValue(int(0.6 * 359))
        self._hue.valueChanged.connect(self._on_hue_changed)
        card_layout.addWidget(self._hue)

        # Hex field
        self._hex = QLineEdit(self._card)
        self._hex.setPlaceholderText("#rrggbb")
        self._hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hex.setMaxLength(7)
        self._hex.setStyleSheet(
            "QLineEdit {"
            "  background: #2a2f45;"
            "  color: #d8d8e0;"
            "  border: 1px solid #3a3f55;"
            "  border-radius: 4px;"
            "  padding: 4px 8px;"
            "  font-family: monospace;"
            "}"
        )
        self._hex.editingFinished.connect(lambda: self.set_hex(self._hex.text()))
        card_layout.addWidget(self._hex)

        # Presets row
        presets_row = QWidget(self._card)
        presets_layout = QHBoxLayout(presets_row)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(4)

        auto_btn = QPushButton("Auto", presets_row)
        auto_btn.setObjectName("autoPreset")
        auto_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent;"
            "  color: #9a9ab8;"
            "  border: 1px dashed #3a3f55;"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "}"
            "QPushButton:hover { border-color: #4a7cff; color: #d8d8e0; }"
        )
        auto_btn.clicked.connect(self.choose_auto)
        presets_layout.addWidget(auto_btn)

        for hex_ in _PRESETS:
            btn = QPushButton(presets_row)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_}; border: 1px solid #4a5070; border-radius: 4px; }}"
                f"QPushButton:hover {{ border: 2px solid #ffffff; }}"
            )
            btn.clicked.connect(lambda _=False, h=hex_: self.set_hex(h))
            presets_layout.addWidget(btn)

        presets_layout.addStretch()
        card_layout.addWidget(presets_row)

        # Saved colors row (rebuilt dynamically)
        self._saved_container = QWidget(self._card)
        self._saved_layout = QHBoxLayout(self._saved_container)
        self._saved_layout.setContentsMargins(0, 0, 0, 0)
        self._saved_layout.setSpacing(4)
        card_layout.addWidget(self._saved_container)

        # OK button
        ok_btn = QPushButton("OK", self._card)
        ok_btn.setObjectName("okButton")
        ok_btn.setStyleSheet(
            "QPushButton {"
            "  background: #4a7cff;"
            "  color: #ffffff;"
            "  border-radius: 5px;"
            "  padding: 5px 20px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background: #5a8cff; }"
        )
        ok_btn.clicked.connect(self.commit)
        card_layout.addWidget(ok_btn, 0, Qt.AlignmentFlag.AlignRight)

        # Size the card once before first show
        self._card.adjustSize()

    def _center_card(self) -> None:
        if self.width() > 0 and self.height() > 0:
            self._card.move(
                (self.width() - self._card.width()) // 2,
                (self.height() - self._card.height()) // 2,
            )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._card.adjustSize()
        self._center_card()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 9, 13, 140))

    def mousePressEvent(self, e):
        # Scrim click (outside the card) cancels the picker
        if not self._card.geometry().contains(e.position().toPoint()):
            self.cancel()
        super().mousePressEvent(e)

    def _on_hue_changed(self, val: int) -> None:
        h = val / 359.0
        _, s, v = self._square.hsv()
        self._square.set_hsv(h, s, v)
        self._sync_hex()

    def _on_square_changed(self) -> None:
        self._sync_hex()

    def _sync_hex(self, emit: bool = True) -> None:
        """Recompute hex from hue slider + square s/v, update the field and optionally emit."""
        h = self._hue.value() / 359.0
        _, s, v = self._square.hsv()
        normalized = QColor.fromHsvF(h, s, v).name()
        self._hex.setText(normalized)
        if emit:
            self.color_live.emit(normalized)

    def _rebuild_saved(self) -> None:
        """Clear and repopulate the saved-colors row."""
        while self._saved_layout.count():
            item = self._saved_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        for i, hex_ in enumerate(self._store.get()):
            slot = QWidget(self._saved_container)
            slot.setObjectName("savedSlot")
            slot_row = QHBoxLayout(slot)
            slot_row.setContentsMargins(0, 0, 0, 0)
            slot_row.setSpacing(1)

            color_btn = QPushButton(slot)
            color_btn.setFixedSize(22, 22)
            color_btn.setStyleSheet(
                f"QPushButton {{ background: {hex_}; border: 1px solid #4a5070; border-radius: 4px; }}"
            )
            color_btn.clicked.connect(lambda _=False, h=hex_: self.set_hex(h))
            slot_row.addWidget(color_btn)

            del_btn = QPushButton("×", slot)
            del_btn.setFixedSize(11, 11)
            del_btn.setStyleSheet(
                "QPushButton {"
                "  background: #e74a4a;"
                "  color: white;"
                "  border-radius: 2px;"
                "  font-size: 7px;"
                "  padding: 0;"
                "}"
            )

            def _make_del(idx: int):
                def _handler(_=False):
                    self._store.clear(idx)
                    self._rebuild_saved()
                return _handler

            del_btn.clicked.connect(_make_del(i))
            slot_row.addWidget(del_btn)

            slot.adjustSize()
            self._saved_layout.addWidget(slot)

        # Trailing '+' button
        add_btn = QPushButton("+", self._saved_container)
        add_btn.setFixedSize(22, 22)
        add_btn.setStyleSheet(
            "QPushButton {"
            "  background: #2a2f45;"
            "  color: #9a9ab8;"
            "  border: 1px dashed #4a5070;"
            "  border-radius: 4px;"
            "  font-size: 14px;"
            "}"
        )
        add_btn.clicked.connect(self.save_current)
        self._saved_layout.addWidget(add_btn)
        self._saved_layout.addStretch()

        self._card.adjustSize()
        self._center_card()
