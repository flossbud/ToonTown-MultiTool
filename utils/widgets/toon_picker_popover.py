"""ToonPickerPopover - popup listing a Launch account's saved toons.

Opened by clicking the primary-toon portrait in an account tile; clicking a
row emits `picked` with that toon's name so the caller can set it primary.

Each row's 24px mini race face reuses the same paint recipe as
PrimaryToonSlot (portrait_bg circle + a lighten_rgb-tinted silhouette +
an accent ring), rasterized once per row onto a QPixmap.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

from utils.color_math import alpha as css_alpha
from utils.color_math import lighten_rgb, with_alpha
from utils.recent_toons import ToonRecord
from utils.shared_widgets import ElidingLabel
from utils.theme_manager import V2_ACCENTS
from utils.toon_silhouette import paint_race_silhouette

POPOVER_WIDTH = 236
FACE_SIZE = 24
FACE_SIL_FRACTION = 0.76
FACE_RING_W = 2
HEART_HEX = "#e05252"


def _tokens(is_dark: bool) -> dict:
    if is_dark:
        return {
            "pop_bg": "#1f1f1f",
            "pop_border": "#3a3a3a",
            "pop_hover": css_alpha("#ffffff", 0.07),
            "pop_label": "#888888",
            "text": "#ffffff",
            "sub": css_alpha("#ffffff", 0.62),
            "portrait_bg": with_alpha("#000000", 0.22),
        }
    return {
        "pop_bg": "#ffffff",
        "pop_border": "#cbd5e1",
        "pop_hover": css_alpha("#0f172a", 0.06),
        "pop_label": "#64748b",
        "text": "#0f172a",
        "sub": css_alpha("#0f172a", 0.55),
        "portrait_bg": with_alpha("#0f172a", 0.06),
    }


def _game_accent(game: str) -> str:
    return V2_ACCENTS.get(game, V2_ACCENTS["ttr"])["c"]


def _face_pixmap(rec: ToonRecord, t: dict) -> QPixmap:
    """Render the 24px circular mini face: the account's real toon portrait
    (same source as the emblem radial accounts ring) when it is cached, else a
    tinted race silhouette fallback."""
    accent_hex = rec.accent or _game_accent(rec.game)
    circle_rect = QRectF(0, 0, FACE_SIZE, FACE_SIZE)
    ring_rect = circle_rect.adjusted(
        FACE_RING_W / 2, FACE_RING_W / 2, -FACE_RING_W / 2, -FACE_RING_W / 2)

    # Real toon portrait from the radial-menu source (disk-cache synchronous).
    if rec.dna:
        try:
            from utils.overlay.radial_portrait import render_account_portrait
            render = render_account_portrait(
                rec.game, rec.toon_name, rec.dna, None, FACE_SIZE)
            if render.status == "complete":
                pm = QPixmap(FACE_SIZE, FACE_SIZE)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(0, 0, render.pixmap)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(accent_hex), FACE_RING_W))
                p.drawEllipse(ring_rect)
                p.end()
                return pm
        except Exception:
            pass

    # Fallback: portrait_bg circle + tinted race silhouette + accent ring.
    pm = QPixmap(FACE_SIZE, FACE_SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(t["portrait_bg"])
    p.drawEllipse(circle_rect)

    inset = FACE_SIZE * (1 - FACE_SIL_FRACTION) / 2
    sil_rect = circle_rect.adjusted(inset, inset, -inset, -inset).toRect()
    fill_hex = lighten_rgb(QColor(accent_hex), 0.5).name()
    paint_race_silhouette(p, sil_rect, rec.species, fill_hex)

    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(accent_hex), FACE_RING_W))
    p.drawEllipse(ring_rect)
    p.end()
    return pm


class _Row(QFrame):
    """One toon row: mini face, name, optional check mark (laff not shown)."""

    clicked = Signal(str)

    def __init__(self, rec: ToonRecord, *, primary_name: str | None,
                 is_dark: bool, parent=None):
        super().__init__(parent)
        self._name = rec.toon_name
        t = _tokens(is_dark)

        self.setObjectName("toonPickerRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "#toonPickerRow { border-radius: 8px; background: transparent; }"
            f"#toonPickerRow:hover {{ background: {t['pop_hover']}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(8)

        face = QLabel(self)
        face.setFixedSize(FACE_SIZE, FACE_SIZE)
        face.setStyleSheet("background: transparent;")
        face.setPixmap(_face_pixmap(rec, t))
        layout.addWidget(face)

        name = ElidingLabel(rec.toon_name, parent=self)
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        name.setStyleSheet(
            f"color: {t['text']}; font-size: 12.5px; font-weight: 600;"
            " background: transparent;"
        )
        layout.addWidget(name, 1)

        accent_hex = rec.accent or _game_accent(rec.game)
        check = QLabel("✓", self)
        check.setStyleSheet(
            f"color: {accent_hex}; font-size: 12px; font-weight: 700;"
            " background: transparent;"
        )
        check.setVisible(primary_name is not None and rec.toon_name == primary_name)
        layout.addWidget(check)

    def _emit_click(self) -> None:
        self.clicked.emit(self._name)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._emit_click()
        super().mouseReleaseEvent(event)


class ToonPickerPopover(QFrame):
    """Popup listing every saved toon on one account; click a row to pick it."""

    picked = Signal(str)

    def __init__(self, toons: list[ToonRecord], *, primary_name: str | None,
                 is_dark: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("toonPickerPopover")
        self.setWindowFlags(Qt.Popup)
        self.setFixedWidth(POPOVER_WIDTH)

        t = _tokens(is_dark)
        self.setStyleSheet(
            "#toonPickerPopover {"
            f" background: {t['pop_bg']};"
            f" border: 1px solid {t['pop_border']};"
            " border-radius: 12px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)

        header = QLabel("PRIMARY TOON", self)
        header.setStyleSheet(
            f"color: {t['pop_label']}; font-size: 10px; font-weight: 700;"
            " letter-spacing: 0.6px; padding: 5px 9px 4px; background: transparent;"
        )
        layout.addWidget(header)

        self.rows: list[_Row] = []
        for rec in toons:
            row = _Row(rec, primary_name=primary_name, is_dark=is_dark, parent=self)
            row.clicked.connect(self.picked.emit)
            layout.addWidget(row)
            self.rows.append(row)

    def open_at(self, global_point) -> None:
        self.move(global_point)
        self.show()
