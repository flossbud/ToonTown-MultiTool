"""Section widgets for the toon customization editor.

Extracted from toon_customization_dialog.py to allow reuse from the
new in-app overlay panel without depending on a QDialog shell.
No behavior change.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.toon_pattern_assets import PATTERN_NAMES
from utils.widgets.pose_thumb_states import paint_shimmer, paint_failed_mark
# ColorWell is imported lazily inside the constructors that need it to
# avoid a circular import: color_picker_overlay imports PRESET_SWATCHES
# from this module, so a top-level ColorWell import here would form a cycle.


# Curated 12-color palette. Order matters - first row primaries, second
# row accents, third row neutrals.
PRESET_SWATCHES = (
    "#e74a4a", "#e7894a", "#d9a04e", "#e6d35a",
    "#56c856", "#4ae7d9", "#4a8fe7", "#4a5fe7",
    "#b04ae7", "#e74ab0", "#7a7a8a", "#1a1d29",
)


class _SwatchRow(QWidget):
    """Default swatch + 12 presets + Custom button. Emits color_picked(hex or None).
    None means 'Default' (remove the field from the draft)."""

    color_picked = Signal(object)  # str (hex) or None

    def __init__(self, current: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._current = current  # hex or None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        # Default swatch first
        self._default_btn = QPushButton("Default")
        self._default_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9a9aa8; "
            "border: 1px dashed #555a70; border-radius: 4px; padding: 0 8px; }"
            "QPushButton:checked { border: 2px solid #fff; color: #fff; }"
        )
        self._default_btn.setCheckable(True)
        self._default_btn.clicked.connect(lambda: self._select(None))
        outer.addWidget(self._default_btn)
        self._preset_btns: list[QPushButton] = []
        for hex_ in PRESET_SWATCHES:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_}; "
                f"border: 1px solid #4a5070; border-radius: 4px; }}"
                f"QPushButton:checked {{ border: 2px solid #fff; }}"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, h=hex_: self._select(h))
            outer.addWidget(btn)
            self._preset_btns.append(btn)
        self._custom_btn = QPushButton("…")
        self._custom_btn.setFixedSize(22, 22)
        self._custom_btn.setStyleSheet(
            "QPushButton { background: #3a3f55; color: #d8d8e0; "
            "border: 1px dashed #6a6f85; border-radius: 4px; }"
        )
        self._custom_btn.clicked.connect(self._open_color_dialog)
        outer.addWidget(self._custom_btn)
        outer.addStretch(1)
        self._refresh_checked()

    def _select(self, hex_: Optional[str]) -> None:
        self._current = hex_
        self._refresh_checked()
        self.color_picked.emit(hex_)

    def _refresh_checked(self) -> None:
        self._default_btn.setChecked(self._current is None)
        for btn, hex_ in zip(self._preset_btns, PRESET_SWATCHES):
            btn.setChecked(hex_ == self._current)

    def _open_color_dialog(self) -> None:
        initial = QColor(self._current) if self._current else QColor("#ffffff")
        chosen = QColorDialog.getColor(initial, self, "Pick a color")
        if chosen.isValid():
            self._select(chosen.name())

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, hex_: Optional[str]) -> None:
        self._current = hex_
        self._refresh_checked()


class _SimpleColorSection(QWidget):
    """A section that contains a single label + one ColorWell."""

    color_changed = Signal(object)  # str or None

    def __init__(self, label: str, current: Optional[str], saved_store=None, parent=None):
        from utils.widgets.color_well import ColorWell
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        title = QLabel(label)
        title.setStyleSheet("color: #c8c8d8; font-weight: bold;")
        outer.addWidget(title)
        self._row = ColorWell(current, saved_store=saved_store)
        self._row.color_picked.connect(self.color_changed.emit)
        outer.addWidget(self._row)
        outer.addStretch(1)

    def current(self) -> Optional[str]:
        return self._row.current()

    def set_current(self, hex_: Optional[str]) -> None:
        self._row.set_current(hex_)


class _ChipRow(QWidget):
    """A row of mutually-exclusive chip buttons. Used for picking from
    a small fixed set of named values (thin/medium/thick,
    subtle/medium/strong, etc). Emits value_changed(str) with the key.
    Mirrors _SwatchRow's API surface."""

    value_changed = Signal(object)  # str (key) - never None

    def __init__(
        self,
        options: list[tuple[str, str]],
        current: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._current = current if current in {k for k, _ in options} else (
            options[0][0] if options else None
        )
        self._enabled_visual = True
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._chip_btns: dict[str, QPushButton] = {}
        for key, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            outer.addWidget(btn)
            self._chip_btns[key] = btn
        outer.addStretch(1)
        self._refresh_checked()
        self._refresh_enabled_style()

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, key: Optional[str]) -> None:
        if key is None or key not in self._chip_btns:
            return
        self._current = key
        self._refresh_checked()

    def set_enabled_visual(self, enabled: bool) -> None:
        self._enabled_visual = enabled
        self._refresh_enabled_style()

    def click_chip(self, key: str) -> None:
        """Programmatic chip click (for tests)."""
        if not self._enabled_visual:
            return
        if key not in self._chip_btns:
            return
        self._select(key)

    def _select(self, key: str) -> None:
        if not self._enabled_visual:
            return
        self._current = key
        self._refresh_checked()
        self.value_changed.emit(key)

    def _refresh_checked(self) -> None:
        for k, btn in self._chip_btns.items():
            btn.setChecked(k == self._current)

    def _refresh_enabled_style(self) -> None:
        for btn in self._chip_btns.values():
            btn.setEnabled(self._enabled_visual)


class _PoseTile(QFrame):
    """One pose option. Shows a circular crop of the fetched pixmap on
    a slot-default-grey backdrop, with the pose name underneath. Click
    to select. The tile itself does NOT apply user customizations -
    the user is choosing the pose so we show it raw.

    State machine:
      loading - shimmer animates, no pixmap yet; clicks are ignored.
      loaded  - pixmap displayed; click emits clicked_pose.
      failed  - X mark shown (timeout or explicit failure); click emits
                retry_requested and returns to loading.
    """

    clicked_pose = Signal(str)
    retry_requested = Signal(str)

    _TILE_W = 160  # wide enough for the bigger label-free thumbnail
    _TILE_H = 110  # box + small padding only; labels live in tooltips
    _BOX = 100
    _CIRCLE_INSET = 10  # circle margin inside the box (scaled with _BOX)
    _BACKDROP = QColor("#4a4a4a")
    _LOAD_TIMEOUT_MS = 8000  # max wait before tile transitions to failed

    # Internal state sentinels (not part of the public API).
    _ST_LOADING = "loading"
    _ST_LOADED = "loaded"
    _ST_FAILED = "failed"

    def __init__(self, pose: str, parent=None):
        super().__init__(parent)
        self._pose = pose
        self._selected = False

        self.setFixedSize(QSize(self._TILE_W, self._TILE_H))
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setToolTip(pose)

        # Shimmer animation - advance phase at ~25 fps.
        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(40)
        self._shimmer_timer.timeout.connect(self._on_shimmer_tick)

        # Load timeout - if no pixmap arrives in time, flip to failed.
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(self._LOAD_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_load_timeout)

        self._enter_loading()

    # -- Public API ----------------------------------------------------------

    @property
    def pose(self) -> str:
        return self._pose

    def is_loading(self) -> bool:
        return self._state == self._ST_LOADING

    def is_failed(self) -> bool:
        return self._state == self._ST_FAILED

    def is_selected(self) -> bool:
        return self._selected

    def has_pixmap(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        """Provide (or clear) the thumbnail pixmap.

        If *pixmap* is a valid, non-null pixmap: transition to loaded.
        If *pixmap* is None or null: reset to loading (restart shimmer +
        timeout), used by the refresh flow.
        """
        if pixmap is not None and not pixmap.isNull():
            self._pixmap = pixmap
            self._state = self._ST_LOADED
            self._stop_loading_timers()
        else:
            self._enter_loading()
        self.update()

    def set_failed(self) -> None:
        """Transition to failed state - stops animation and shows the X mark."""
        self._state = self._ST_FAILED
        self._stop_loading_timers()
        self.update()

    def set_selected(self, on: bool) -> None:
        if self._selected != on:
            self._selected = on
            self.update()

    # -- Internal state helpers ----------------------------------------------

    def _enter_loading(self) -> None:
        """Transition to loading state: clear pixmap, reset shimmer, restart timers."""
        self._pixmap = None
        self._state = self._ST_LOADING
        self._shimmer_phase = 0.0
        self._shimmer_timer.start()
        self._timeout_timer.start()

    # -- Click logic (shared by mouse event and test hook) -------------------

    def _handle_click(self) -> None:
        """Apply the click action appropriate for the current state."""
        if self._state == self._ST_FAILED:
            # A broken thumbnail offers retry, not selection.
            self._enter_loading()
            self.update()
            self.retry_requested.emit(self._pose)
        else:
            # Loaded OR loading: selecting the pose works regardless of the
            # thumbnail state. Selection must not be gated on the rendition
            # fetch, a slow or failing thumbnail must never block picking a pose.
            self.clicked_pose.emit(self._pose)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._handle_click()
        super().mousePressEvent(event)

    # -- Timer handlers ------------------------------------------------------

    def _on_shimmer_tick(self) -> None:
        self._shimmer_phase = (self._shimmer_phase + 0.025) % 1.0
        self.update()

    def _on_load_timeout(self) -> None:
        """Called when the load timeout fires. If still loading, fail."""
        if self._state == self._ST_LOADING:
            self.set_failed()

    def _stop_loading_timers(self) -> None:
        self._shimmer_timer.stop()
        self._timeout_timer.stop()

    # -- Paint ---------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if self._selected:
            p.fillRect(self.rect(), QColor(74, 124, 255, 60))

        # Center the box horizontally in the (possibly wider) tile.
        box_x = (self._TILE_W - self._BOX) // 2
        box = QRect(box_x, 0, self._BOX, self._BOX)
        circle = box.adjusted(
            self._CIRCLE_INSET, self._CIRCLE_INSET,
            -self._CIRCLE_INSET, -self._CIRCLE_INSET,
        )
        p.setPen(Qt.NoPen)
        p.setBrush(self._BACKDROP)
        p.drawEllipse(circle)

        if self._state == self._ST_LOADED and self.has_pixmap():
            path = QPainterPath()
            path.addEllipse(circle)
            p.save()
            p.setClipPath(path)
            scaled = self._pixmap.scaled(
                circle.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            dx = circle.x() + (circle.width() - scaled.width()) // 2
            dy = circle.y() + (circle.height() - scaled.height()) // 2
            p.drawPixmap(dx, dy, scaled)
            p.restore()
        elif self._state == self._ST_LOADING:
            paint_shimmer(p, circle, self._shimmer_phase)
        elif self._state == self._ST_FAILED:
            paint_failed_mark(p, circle)

        p.end()


class _PoseAdjustPreview(QFrame):
    """Large circular preview that the user drags / scrolls to adjust
    the toon's transform. ~180 px diameter. Emits transform_changed
    whenever offset_x / offset_y / zoom changes via user interaction."""

    transform_changed = Signal()

    _SIZE = 140
    _BACKDROP = QColor("#1a1d29")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._off_x: float = 0.0
        self._off_y: float = 0.0
        self._rotate: float = 0.0
        self._dragging: bool = False
        self._drag_anchor: Optional[QPoint] = None
        self._drag_initial_off: tuple[float, float] = (0.0, 0.0)
        self.setFixedSize(QSize(self._SIZE, self._SIZE))
        self.setCursor(Qt.OpenHandCursor)
        self.setFrameShape(QFrame.NoFrame)

    # -- Public API ----------------------------------------------------------

    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def set_pixmap(self, pm: Optional[QPixmap]) -> None:
        self._pixmap = pm
        self.update()

    def transform(self) -> tuple[float, float, float, float]:
        return (self._zoom, self._off_x, self._off_y, self._rotate)

    def set_transform(
        self, zoom: float, off_x: float, off_y: float, rotate: float
    ) -> None:
        self._zoom = max(0.5, min(3.0, float(zoom)))
        self._off_x = max(-1.0, min(1.0, float(off_x)))
        self._off_y = max(-1.0, min(1.0, float(off_y)))
        r = float(rotate)
        while r > 180.0:
            r -= 360.0
        while r < -180.0:
            r += 360.0
        self._rotate = r
        self.update()

    # -- Mouse / wheel -------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_anchor = event.pos()
            self._drag_initial_off = (self._off_x, self._off_y)
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_anchor is not None:
            dx = event.pos().x() - self._drag_anchor.x()
            dy = event.pos().y() - self._drag_anchor.y()
            new_x = self._drag_initial_off[0] + (dx / self._SIZE)
            new_y = self._drag_initial_off[1] + (dy / self._SIZE)
            self._off_x = max(-1.0, min(1.0, new_x))
            self._off_y = max(-1.0, min(1.0, new_y))
            self.update()
            self.transform_changed.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_anchor = None
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # One notch (120 angleDelta units) = ±0.05 zoom.
        delta = event.angleDelta().y() / 120.0
        new_zoom = self._zoom + (0.05 * delta)
        new_zoom = max(0.5, min(3.0, new_zoom))
        if new_zoom != self._zoom:
            self._zoom = new_zoom
            self.update()
            self.transform_changed.emit()
        event.accept()

    # -- Paint --------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(self._BACKDROP)
        p.drawEllipse(rect)
        if self._pixmap is not None and not self._pixmap.isNull():
            ox = int(self._off_x * rect.width())
            oy = int(self._off_y * rect.height())
            path = QPainterPath()
            path.addEllipse(rect)
            p.save()
            p.setClipPath(path)
            p.translate(rect.center())
            p.rotate(self._rotate)
            p.scale(self._zoom, self._zoom)
            p.translate(ox, oy)
            scaled = self._pixmap.scaled(
                rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            p.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
            p.restore()
        p.end()


class _PoseAdjustView(QWidget):
    """Adjust mode for the Toon section: drag-to-pan preview + zoom
    slider + rotate slider + nudge arrow buttons + Back / Reset buttons
    in the header. Emits transform_changed whenever any control changes
    a value. Back / Reset have their own signals so _PoseSection can
    drive the state transition."""

    transform_changed = Signal()
    back_requested = Signal()
    reset_requested = Signal()
    silhouette_outline_changed = Signal(object, object)  # (hex or None, width key)
    silhouette_shadow_changed = Signal(object, object)  # (hex or None, softness key)

    _NUDGE_STEP = 1.0 / 180.0  # one pixel in the 180 px adjust preview

    def __init__(self, initial: tuple[float, float, float, float], saved_store=None, parent=None):
        super().__init__(parent)
        zoom, off_x, off_y, rot = initial
        self._build_ui(zoom, off_x, off_y, rot, saved_store=saved_store)

    def _build_ui(
        self, zoom: float, off_x: float, off_y: float, rot: float, saved_store=None,
    ) -> None:
        from utils.widgets.color_well import ColorWell
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Header row: Back + Reset (right-aligned)
        header = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self.back_requested.emit)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        header.addStretch(1)
        header.addWidget(self._back_btn)
        header.addWidget(self._reset_btn)
        outer.addLayout(header)

        # Preview (centered) + nudge row underneath
        self._preview = _PoseAdjustPreview()
        self._preview.set_transform(zoom, off_x, off_y, rot)
        self._preview.transform_changed.connect(self._on_preview_changed)
        outer.addWidget(self._preview, alignment=Qt.AlignHCenter)

        nudge = QHBoxLayout()
        nudge.setSpacing(2)
        nudge.addStretch(1)
        self._left_btn = QPushButton("←")
        self._left_btn.setFixedWidth(28)
        self._left_btn.clicked.connect(self.nudge_left)
        self._up_btn = QPushButton("↑")
        self._up_btn.setFixedWidth(28)
        self._up_btn.clicked.connect(self.nudge_up)
        self._down_btn = QPushButton("↓")
        self._down_btn.setFixedWidth(28)
        self._down_btn.clicked.connect(self.nudge_down)
        self._right_btn = QPushButton("→")
        self._right_btn.setFixedWidth(28)
        self._right_btn.clicked.connect(self.nudge_right)
        for btn in (self._left_btn, self._up_btn, self._down_btn, self._right_btn):
            nudge.addWidget(btn)
        nudge.addStretch(1)
        outer.addLayout(nudge)

        # Zoom slider
        zoom_label = QLabel("Zoom")
        zoom_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        outer.addWidget(zoom_label)
        zoom_row = QHBoxLayout()
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setRange(50, 300)  # 0.5x to 3.0x in 0.01 steps
        self._zoom_slider.setValue(int(zoom * 100))
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        zoom_row.addWidget(self._zoom_slider)
        self._zoom_value = QLabel(f"{zoom:.2f}x")
        self._zoom_value.setFixedWidth(48)
        zoom_row.addWidget(self._zoom_value)
        outer.addLayout(zoom_row)

        # Rotate slider
        rot_label = QLabel("Rotate")
        rot_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        outer.addWidget(rot_label)
        rot_row = QHBoxLayout()
        self._rot_slider = QSlider(Qt.Horizontal)
        self._rot_slider.setRange(-180, 180)
        self._rot_slider.setValue(int(rot))
        self._rot_slider.valueChanged.connect(self._on_rot_slider)
        rot_row.addWidget(self._rot_slider)
        self._rot_value = QLabel(f"{int(rot)}°")
        self._rot_value.setFixedWidth(48)
        rot_row.addWidget(self._rot_value)
        outer.addLayout(rot_row)

        # Silhouette outline section
        outline_label = QLabel("Outline (toon)")
        outline_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        outer.addWidget(outline_label)
        self._sil_outline_color_row = ColorWell(None, saved_store=saved_store)
        self._sil_outline_color_row.color_picked.connect(self._on_sil_outline_color)
        outer.addWidget(self._sil_outline_color_row)
        self._sil_outline_chip = _ChipRow(
            [("thin", "Thin"), ("medium", "Medium"), ("thick", "Thick")],
            current="medium",
        )
        self._sil_outline_chip.value_changed.connect(self._on_sil_outline_width)
        self._sil_outline_chip.set_enabled_visual(False)
        outer.addWidget(self._sil_outline_chip)

        # Silhouette shadow section
        shadow_label = QLabel("Shadow (toon)")
        shadow_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        outer.addWidget(shadow_label)
        self._sil_shadow_color_row = ColorWell(None, saved_store=saved_store)
        self._sil_shadow_color_row.color_picked.connect(self._on_sil_shadow_color)
        outer.addWidget(self._sil_shadow_color_row)
        self._sil_shadow_chip = _ChipRow(
            [("subtle", "Subtle"), ("medium", "Medium"), ("strong", "Strong")],
            current="medium",
        )
        self._sil_shadow_chip.value_changed.connect(self._on_sil_shadow_softness)
        self._sil_shadow_chip.set_enabled_visual(False)
        outer.addWidget(self._sil_shadow_chip)

        outer.addStretch(1)

    # -- Public API ----------------------------------------------------------

    def transform(self) -> tuple[float, float, float, float]:
        return self._preview.transform()

    def set_pixmap(self, pm: Optional[QPixmap]) -> None:
        self._preview.set_pixmap(pm)

    def set_zoom(self, zoom: float) -> None:
        """Programmatic setter (also drives the slider)."""
        self._zoom_slider.setValue(int(zoom * 100))

    def set_rotate(self, rot: float) -> None:
        self._rot_slider.setValue(int(rot))

    def nudge_left(self) -> None:
        self._apply_nudge(-self._NUDGE_STEP, 0.0)

    def nudge_right(self) -> None:
        self._apply_nudge(self._NUDGE_STEP, 0.0)

    def nudge_up(self) -> None:
        self._apply_nudge(0.0, -self._NUDGE_STEP)

    def nudge_down(self) -> None:
        self._apply_nudge(0.0, self._NUDGE_STEP)

    def click_back(self) -> None:
        self.back_requested.emit()

    def click_reset(self) -> None:
        self._on_reset_clicked()

    # -- Internal ------------------------------------------------------------

    def _apply_nudge(self, dx: float, dy: float) -> None:
        z, ox, oy, r = self._preview.transform()
        self._preview.set_transform(z, ox + dx, oy + dy, r)
        self.transform_changed.emit()

    def _on_zoom_slider(self, value: int) -> None:
        zoom = value / 100.0
        z, ox, oy, r = self._preview.transform()
        self._preview.set_transform(zoom, ox, oy, r)
        self._zoom_value.setText(f"{zoom:.2f}x")
        self.transform_changed.emit()

    def _on_rot_slider(self, value: int) -> None:
        z, ox, oy, _ = self._preview.transform()
        self._preview.set_transform(z, ox, oy, float(value))
        self._rot_value.setText(f"{value}°")
        self.transform_changed.emit()

    def _on_preview_changed(self) -> None:
        """The preview emits this when the user drags or scrolls. Sync
        sliders to the new values and re-emit upward."""
        z, ox, oy, r = self._preview.transform()
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(z * 100))
        self._zoom_slider.blockSignals(False)
        self._zoom_value.setText(f"{z:.2f}x")
        self.transform_changed.emit()

    def _on_reset_clicked(self) -> None:
        self._preview.set_transform(1.0, 0.0, 0.0, 0.0)
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(100)
        self._zoom_slider.blockSignals(False)
        self._rot_slider.blockSignals(True)
        self._rot_slider.setValue(0)
        self._rot_slider.blockSignals(False)
        self._zoom_value.setText("1.00x")
        self._rot_value.setText("0°")
        self.transform_changed.emit()
        self.reset_requested.emit()
        # Clear silhouette outline + shadow alongside the transform reset.
        # The two silhouette pickers below the sliders also get cleared visually.
        self._sil_outline_color_row.set_current(None)
        self._sil_outline_chip.set_enabled_visual(False)
        self._sil_shadow_color_row.set_current(None)
        self._sil_shadow_chip.set_enabled_visual(False)
        self.silhouette_outline_changed.emit(None, self._sil_outline_chip.current())
        self.silhouette_shadow_changed.emit(None, self._sil_shadow_chip.current())

    def _on_sil_outline_color(self, hex_: Optional[str]) -> None:
        self._sil_outline_chip.set_enabled_visual(hex_ is not None)
        self.silhouette_outline_changed.emit(hex_, self._sil_outline_chip.current())

    def _on_sil_outline_width(self, width_key: str) -> None:
        self.silhouette_outline_changed.emit(
            self._sil_outline_color_row.current(), width_key,
        )

    def set_silhouette_outline_from_draft(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        """Initial-state setter used by _PoseSection when entering the
        Adjust view. Does NOT emit silhouette_outline_changed - the
        dialog's draft already has this value."""
        self._sil_outline_color_row.set_current(hex_)
        if width_key:
            self._sil_outline_chip.set_current(width_key)
        self._sil_outline_chip.set_enabled_visual(hex_ is not None)

    def silhouette_outline(self) -> tuple[Optional[str], str]:
        return self._sil_outline_color_row.current(), self._sil_outline_chip.current()

    def _on_sil_shadow_color(self, hex_: Optional[str]) -> None:
        self._sil_shadow_chip.set_enabled_visual(hex_ is not None)
        self.silhouette_shadow_changed.emit(hex_, self._sil_shadow_chip.current())

    def _on_sil_shadow_softness(self, softness_key: str) -> None:
        self.silhouette_shadow_changed.emit(
            self._sil_shadow_color_row.current(), softness_key,
        )

    def set_silhouette_shadow_from_draft(
        self, hex_: Optional[str], softness_key: Optional[str],
    ) -> None:
        """Initial-state setter used by _PoseSection. Does NOT emit -
        the dialog's draft already has this value."""
        self._sil_shadow_color_row.set_current(hex_)
        if softness_key:
            self._sil_shadow_chip.set_current(softness_key)
        self._sil_shadow_chip.set_enabled_visual(hex_ is not None)

    def silhouette_shadow(self) -> tuple[Optional[str], str]:
        return self._sil_shadow_color_row.current(), self._sil_shadow_chip.current()


class _PoseSection(QWidget):
    """Toon pose picker, 2-state. Page 0 = grid of 13 pose tiles. Page 1
    = adjust view (drag + sliders + nudge). The user enters page 1 via
    the 'Adjust' button in page 0's header; Back returns to page 0."""

    pose_changed = Signal(str)
    transform_changed = Signal()  # emitted when adjust view writes to transform
    silhouette_outline_changed = Signal(object, object)  # (hex or None, width key)
    silhouette_shadow_changed = Signal(object, object)  # (hex or None, softness key)

    def __init__(self, dna: Optional[str], current_pose: str, saved_store=None, parent=None):
        super().__init__(parent)
        self._dna = dna
        self._current_pose = current_pose
        self._saved_store = saved_store
        self._tiles: list[_PoseTile] = []
        self._placeholder_label: Optional[QLabel] = None
        self._grid_page: Optional[QWidget] = None
        self._adjust_view: Optional[_PoseAdjustView] = None
        self._stack: Optional[QStackedWidget] = None
        self._adjust_btn: Optional[QPushButton] = None
        self._refresh_btn: Optional[QPushButton] = None
        self._grid_header: Optional[QWidget] = None
        self._header_stack: Optional[QStackedWidget] = None
        # Mirror of the transform values pushed into / out of the adjust
        # view; the dialog reads via _PoseSection.transform().
        self._transform: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
        self._build()

    # -- Build ---------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header is a QStackedWidget so we can swap "grid header"
        # (Pose + Adjust + Refresh) and "adjust header" (Pose + Back +
        # Reset) when the body page changes.
        self._header_stack = QStackedWidget()
        self._header_stack.addWidget(self._build_grid_header())
        # adjust header is built lazily when the adjust view is created.
        outer.addWidget(self._header_stack)

        # Body stack
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        self._grid_page = self._build_grid_page()
        self._stack.addWidget(self._grid_page)

    def _build_grid_header(self) -> QWidget:
        header_w = QWidget()
        header = QHBoxLayout(header_w)
        header.setContentsMargins(8, 8, 8, 4)
        title = QLabel("Pose")
        title.setStyleSheet("color: #c8c8d8; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        self._adjust_btn = QPushButton("Adjust")
        self._adjust_btn.setToolTip("Zoom / pan / rotate the toon inside the circle")
        self._adjust_btn.clicked.connect(self.click_adjust)
        if not self._dna:
            self._adjust_btn.setEnabled(False)
        # Pin Adjust to a known height so refresh (icon-only) matches.
        self._adjust_btn.setFixedHeight(28)
        header.addWidget(self._adjust_btn)
        # Refresh button uses Qt's standard reload icon instead of "↻"
        # text. KDE Breeze elides QPushButton text in tight buttons,
        # which would otherwise render the ↻ glyph as ":" or "...".
        # Icons are never elided.
        from PySide6.QtWidgets import QStyle
        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        from PySide6.QtCore import QSize
        self._refresh_btn.setIconSize(QSize(14, 14))
        self._refresh_btn.setToolTip("Refresh pose thumbnails")
        self._refresh_btn.setFixedSize(32, 28)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        if not self._dna:
            self._refresh_btn.setEnabled(False)
        header.addWidget(self._refresh_btn)
        self._grid_header = header_w
        return header_w

    def _build_grid_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 0, 8, 8)
        outer.setSpacing(6)

        if not self._dna:
            self._placeholder_label = QLabel(
                "Log into this toon to see pose options."
            )
            self._placeholder_label.setStyleSheet("color: #9a9aa8; padding: 24px;")
            self._placeholder_label.setAlignment(Qt.AlignCenter)
            outer.addWidget(self._placeholder_label, 1)
            return page

        from utils.rendition_poses import POSE_NAMES, RenditionPoseFetcher
        grid = QGridLayout()
        grid.setSpacing(6)
        for idx, pose in enumerate(POSE_NAMES):
            tile = _PoseTile(pose)
            tile.set_selected(pose == self._current_pose)
            tile.clicked_pose.connect(self._on_tile_clicked)
            tile.retry_requested.connect(self._on_tile_retry_requested)
            grid.addWidget(tile, idx // 3, idx % 3)
            self._tiles.append(tile)
        outer.addLayout(grid)
        outer.addStretch(1)

        fetcher = RenditionPoseFetcher.instance()
        fetcher.pose_ready.connect(self._on_pose_ready)
        for pose in POSE_NAMES:
            fetcher.request(self._dna, pose)
        return page

    def _build_adjust_header(self) -> QWidget:
        header_w = QWidget()
        header = QHBoxLayout(header_w)
        header.setContentsMargins(8, 8, 8, 4)
        title = QLabel("Pose")
        title.setStyleSheet("color: #c8c8d8; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        # The Back / Reset buttons live INSIDE _PoseAdjustView's own
        # header row; we don't duplicate them here. Just a static label.
        return header_w

    # -- Public API ----------------------------------------------------------

    def tiles(self) -> list:
        return list(self._tiles)

    def has_placeholder(self) -> bool:
        return self._placeholder_label is not None

    def click_refresh(self) -> None:
        self._on_refresh_clicked()

    def is_adjusting(self) -> bool:
        return self._stack is not None and self._stack.currentIndex() == 1

    def _ensure_adjust_view(self) -> None:
        """Create the adjust view lazily on first access. Idempotent."""
        if self._adjust_view is not None:
            return
        self._adjust_view = _PoseAdjustView(initial=self._transform, saved_store=self._saved_store)
        for t in self._tiles:
            if t.pose == self._current_pose and t.has_pixmap():
                self._adjust_view.set_pixmap(t._pixmap)
                break
        self._adjust_view.transform_changed.connect(self._on_adjust_changed)
        self._adjust_view.back_requested.connect(self.click_back)
        self._adjust_view.silhouette_outline_changed.connect(
            self.silhouette_outline_changed.emit
        )
        self._adjust_view.silhouette_shadow_changed.connect(
            self.silhouette_shadow_changed.emit
        )
        self._stack.addWidget(self._adjust_view)
        self._header_stack.addWidget(self._build_adjust_header())

    def click_adjust(self) -> None:
        if not self._dna:
            return
        self._ensure_adjust_view()
        self._stack.setCurrentIndex(1)
        self._header_stack.setCurrentIndex(1)

    def click_back(self) -> None:
        if self._stack is None:
            return
        self._stack.setCurrentIndex(0)
        self._header_stack.setCurrentIndex(0)

    def adjust_view(self) -> Optional["_PoseAdjustView"]:
        return self._adjust_view

    def transform(self) -> tuple[float, float, float, float]:
        return self._transform

    def set_transform_from_draft(
        self, transform: tuple[float, float, float, float],
    ) -> None:
        """Called by the dialog when the section is constructed with a
        pre-existing draft transform."""
        self._transform = transform
        if self._adjust_view is not None:
            self._adjust_view._preview.set_transform(*transform)

    def set_silhouette_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        """Forwarded from the dialog setter. Pushes through to the adjust
        view (creating it if needed) and re-emits so the dialog handler
        writes to the draft."""
        self._ensure_adjust_view()
        self._adjust_view.set_silhouette_outline_from_draft(hex_, width_key)
        self.silhouette_outline_changed.emit(hex_, width_key)

    def set_silhouette_shadow(
        self, hex_: Optional[str], softness_key: Optional[str],
    ) -> None:
        """Forwarded from the dialog setter. Pushes through to the adjust
        view (creating it if needed) and re-emits so the dialog handler
        writes to the draft."""
        self._ensure_adjust_view()
        self._adjust_view.set_silhouette_shadow_from_draft(hex_, softness_key)
        self.silhouette_shadow_changed.emit(hex_, softness_key)

    # -- Signal handlers -----------------------------------------------------

    def _on_tile_clicked(self, pose: str) -> None:
        if pose == self._current_pose:
            return
        self._current_pose = pose
        for t in self._tiles:
            t.set_selected(t.pose == pose)
        if self._adjust_view is not None:
            for t in self._tiles:
                if t.pose == pose and t.has_pixmap():
                    self._adjust_view.set_pixmap(t._pixmap)
                    break
        self.pose_changed.emit(pose)

    def _on_pose_ready(self, dna: str, pose: str, pixmap) -> None:
        if dna != self._dna:
            return
        for t in self._tiles:
            if t.pose == pose:
                if pixmap is None or pixmap.isNull():
                    t.set_failed()
                else:
                    t.set_pixmap(pixmap)
                    if pose == self._current_pose and self._adjust_view is not None:
                        self._adjust_view.set_pixmap(pixmap)
                break

    def _on_tile_retry_requested(self, pose: str) -> None:
        """Re-request a single pose thumbnail after a tile timeout/failure."""
        if not self._dna:
            return
        from utils.rendition_poses import RenditionPoseFetcher
        RenditionPoseFetcher.instance().request(self._dna, pose)

    def _on_refresh_clicked(self) -> None:
        if not self._dna:
            return
        from utils.rendition_poses import RenditionPoseFetcher, POSE_NAMES
        fetcher = RenditionPoseFetcher.instance()
        fetcher.invalidate_dna(self._dna)
        for t in self._tiles:
            t.set_pixmap(None)
        for pose in POSE_NAMES:
            fetcher.request(self._dna, pose)

    def _on_adjust_changed(self) -> None:
        self._transform = self._adjust_view.transform()
        self.transform_changed.emit()

    def closeEvent(self, event):
        try:
            from utils.rendition_poses import RenditionPoseFetcher
            RenditionPoseFetcher.instance().pose_ready.disconnect(
                self._on_pose_ready
            )
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)


class _PortraitSection(QWidget):
    """Portrait color + gradient + pattern controls.

    Holds three sub-controls:
      - color row (default + 12 presets + custom)
      - gradient toggle + 2 color rows (only visible when toggle is on)
      - pattern picker (none + 8 patterns) + pattern color row
        (only visible when a pattern is selected)
    """

    color_changed = Signal(object)         # str or None
    gradient_changed = Signal(object)      # {"start", "end"} or None
    pattern_changed = Signal(object, object)  # (name or None, color or None)
    circle_outline_changed = Signal(object, object)  # (color hex or None, width key str)

    def __init__(self, current: dict, saved_store=None, parent=None):
        from utils.widgets.color_well import ColorWell
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        outer.addWidget(self._label("Color"))
        self._color_row = ColorWell(current.get("color"), saved_store=saved_store)
        self._color_row.color_picked.connect(self.color_changed.emit)
        outer.addWidget(self._color_row)

        outer.addWidget(self._label("Gradient"))
        grad_row = QHBoxLayout()
        self._grad_toggle = QPushButton("Off")
        self._grad_toggle.setCheckable(True)
        self._grad_toggle.setMinimumWidth(60)
        self._grad_toggle.clicked.connect(self._on_gradient_toggle)
        grad_row.addWidget(self._grad_toggle)
        grad_row.addStretch(1)
        outer.addLayout(grad_row)

        self._grad_start = ColorWell(
            (current.get("gradient") or {}).get("start"), saved_store=saved_store,
        )
        self._grad_end = ColorWell(
            (current.get("gradient") or {}).get("end"), saved_store=saved_store,
        )
        self._grad_start.color_picked.connect(lambda _: self._emit_gradient())
        self._grad_end.color_picked.connect(lambda _: self._emit_gradient())
        outer.addWidget(self._grad_start)
        outer.addWidget(self._grad_end)

        outer.addWidget(self._label("Pattern"))
        pat_grid = QGridLayout()
        pat_grid.setHorizontalSpacing(4)
        pat_grid.setVerticalSpacing(4)
        self._pat_buttons: dict[Optional[str], QPushButton] = {}
        none_btn = QPushButton("None")
        none_btn.setCheckable(True)
        fm = none_btn.fontMetrics()
        none_btn.setMinimumWidth(fm.horizontalAdvance(none_btn.text()) + 32)
        none_btn.clicked.connect(lambda: self._select_pattern(None))
        pat_grid.addWidget(none_btn, 0, 0)
        self._pat_buttons[None] = none_btn
        cols = 4
        cell = 1
        for name in PATTERN_NAMES:
            b = QPushButton(name.replace("_", " "))
            b.setCheckable(True)
            fm = b.fontMetrics()
            b.setMinimumWidth(fm.horizontalAdvance(b.text()) + 32)
            b.clicked.connect(lambda _=False, n=name: self._select_pattern(n))
            row, col = divmod(cell, cols)
            pat_grid.addWidget(b, row, col)
            self._pat_buttons[name] = b
            cell += 1
        outer.addLayout(pat_grid)

        outer.addWidget(self._label("Pattern color"))
        self._pat_color_row = ColorWell(
            (current.get("pattern") or {}).get("color"), saved_store=saved_store,
        )
        self._pat_color_row.color_picked.connect(lambda _: self._emit_pattern())
        outer.addWidget(self._pat_color_row)

        outer.addWidget(self._label("Outline"))
        outline_dict = current.get("outline") if isinstance(current.get("outline"), dict) else {}
        self._outline_color_row = ColorWell(outline_dict.get("color"), saved_store=saved_store)
        self._outline_color_row.color_picked.connect(self._on_outline_color_picked)
        outer.addWidget(self._outline_color_row)

        self._outline_chip_row = _ChipRow(
            [("thin", "Thin"), ("medium", "Medium"), ("thick", "Thick")],
            current=outline_dict.get("width", "medium"),
        )
        self._outline_chip_row.value_changed.connect(self._on_outline_width_picked)
        outer.addWidget(self._outline_chip_row)
        self._outline_chip_row.set_enabled_visual(bool(outline_dict.get("color")))

        outer.addStretch(1)

        # Initialize visibility / checked state from `current`.
        grad = current.get("gradient")
        if isinstance(grad, dict):
            self._grad_toggle.setChecked(True)
            self._grad_toggle.setText("On")
        else:
            self._grad_start.setVisible(False)
            self._grad_end.setVisible(False)

        pat = current.get("pattern") or {}
        pat_name = pat.get("name") if isinstance(pat, dict) else None
        self._current_pat = pat_name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(pat_name is not None)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #9a9aa8; font-size: 10px; "
            "text-transform: uppercase; letter-spacing: 0.5px;"
        )
        return lbl

    def _on_gradient_toggle(self) -> None:
        on = self._grad_toggle.isChecked()
        self._grad_toggle.setText("On" if on else "Off")
        self._grad_start.setVisible(on)
        self._grad_end.setVisible(on)
        self._emit_gradient()

    def _emit_gradient(self) -> None:
        if not self._grad_toggle.isChecked():
            self.gradient_changed.emit(None)
            return
        start = self._grad_start.current()
        end = self._grad_end.current()
        if start and end:
            self.gradient_changed.emit({"start": start, "end": end})
        else:
            self.gradient_changed.emit(None)

    def _select_pattern(self, name: Optional[str]) -> None:
        self._current_pat = name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(name is not None)
        self._emit_pattern()

    def _refresh_pat_checked(self) -> None:
        for n, btn in self._pat_buttons.items():
            btn.setChecked(n == self._current_pat)

    def _emit_pattern(self) -> None:
        if self._current_pat is None:
            self.pattern_changed.emit(None, None)
            return
        color = self._pat_color_row.current() or "#ffffff"
        self.pattern_changed.emit(self._current_pat, color)

    # -- programmatic setters (for tests) --------------------------------------

    def set_color(self, hex_: Optional[str]) -> None:
        self._color_row.set_current(hex_)

    def set_gradient(self, grad: Optional[dict]) -> None:
        on = isinstance(grad, dict)
        self._grad_toggle.setChecked(on)
        self._grad_toggle.setText("On" if on else "Off")
        self._grad_start.setVisible(on)
        self._grad_end.setVisible(on)
        if on:
            self._grad_start.set_current(grad.get("start"))
            self._grad_end.set_current(grad.get("end"))

    def set_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        self._current_pat = name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(name is not None)
        if color is not None:
            self._pat_color_row.set_current(color)

    def _on_outline_color_picked(self, hex_: Optional[str]) -> None:
        self._outline_chip_row.set_enabled_visual(hex_ is not None)
        self.circle_outline_changed.emit(hex_, self._outline_chip_row.current())

    def _on_outline_width_picked(self, width_key: str) -> None:
        self.circle_outline_changed.emit(
            self._outline_color_row.current(), width_key,
        )

    def set_circle_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        """Programmatic setter (for tests)."""
        self._outline_color_row.set_current(hex_)
        if width_key is not None:
            self._outline_chip_row.set_current(width_key)
        self._outline_chip_row.set_enabled_visual(hex_ is not None)
        self.circle_outline_changed.emit(hex_, self._outline_chip_row.current())

    def current_circle_outline(self) -> tuple[Optional[str], str]:
        return self._outline_color_row.current(), self._outline_chip_row.current()
