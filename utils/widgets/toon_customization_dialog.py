"""Toon customization picker dialog.

Replaces RacePickerDialog. Sidebar nav + section stack + live preview
+ Save/Cancel/Reset. Sections rendered based on game tag.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.toon_pattern_assets import PATTERN_NAMES
from utils.widgets.card_preview_widget import CardPreviewWidget
from utils.widgets.race_icon_grid import RaceIconGridWidget


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
    """A section that contains a single label + one _SwatchRow."""

    color_changed = Signal(object)  # str or None

    def __init__(self, label: str, current: Optional[str], parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        title = QLabel(label)
        title.setStyleSheet("color: #c8c8d8; font-weight: bold;")
        outer.addWidget(title)
        self._row = _SwatchRow(current)
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
    the user is choosing the pose so we show it raw."""

    clicked_pose = Signal(str)

    _TILE_W = 110  # wide enough for "portrait-delighted" / "portrait-thinking"
    _TILE_H = 100  # box + label
    _BOX = 80
    _CIRCLE_INSET = 8  # circle margin inside the box
    _BACKDROP = QColor("#4a4a4a")

    def __init__(self, pose: str, parent=None):
        super().__init__(parent)
        self._pose = pose
        self._pixmap: Optional[QPixmap] = None
        self._selected = False
        self.setFixedSize(QSize(self._TILE_W, self._TILE_H))
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)

    # -- Public API ----------------------------------------------------------

    @property
    def pose(self) -> str:
        return self._pose

    def is_selected(self) -> bool:
        return self._selected

    def has_pixmap(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self.update()

    def set_selected(self, on: bool) -> None:
        if self._selected != on:
            self._selected = on
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked_pose.emit(self._pose)
        super().mousePressEvent(event)

    # -- Paint --------------------------------------------------------------

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

        if self.has_pixmap():
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
        else:
            p.setPen(QColor("#9a9aa8"))
            p.drawText(circle, Qt.AlignCenter, "…")

        p.setPen(QColor("#c8c8d8"))
        label_rect = QRect(0, self._BOX + 2, self.width(), self.height() - self._BOX - 2)
        p.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, self._pose)
        p.end()


class _PoseAdjustPreview(QFrame):
    """Large circular preview that the user drags / scrolls to adjust
    the toon's transform. ~180 px diameter. Emits transform_changed
    whenever offset_x / offset_y / zoom changes via user interaction."""

    transform_changed = Signal()

    _SIZE = 180
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

    _NUDGE_STEP = 1.0 / 180.0  # one pixel in the 180 px adjust preview

    def __init__(self, initial: tuple[float, float, float, float], parent=None):
        super().__init__(parent)
        zoom, off_x, off_y, rot = initial
        self._build_ui(zoom, off_x, off_y, rot)

    def _build_ui(
        self, zoom: float, off_x: float, off_y: float, rot: float,
    ) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Header row: Back + Reset
        header = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self.back_requested.emit)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        header.addStretch(1)
        header.addWidget(self._back_btn)
        header.addWidget(self._reset_btn)
        outer.addLayout(header)

        # Body: preview on the left, controls on the right
        body = QHBoxLayout()
        body.setSpacing(16)

        # Left column: preview + nudge buttons
        left = QVBoxLayout()
        left.setSpacing(4)
        self._preview = _PoseAdjustPreview()
        self._preview.set_transform(zoom, off_x, off_y, rot)
        self._preview.transform_changed.connect(self._on_preview_changed)
        left.addWidget(self._preview, alignment=Qt.AlignHCenter)

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
        left.addLayout(nudge)
        body.addLayout(left)

        # Right column: sliders + value labels
        right = QVBoxLayout()
        right.setSpacing(10)

        zoom_label = QLabel("Zoom")
        zoom_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        right.addWidget(zoom_label)
        zoom_row = QHBoxLayout()
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setRange(50, 300)  # 0.5x to 3.0x in 0.01 steps
        self._zoom_slider.setValue(int(zoom * 100))
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        zoom_row.addWidget(self._zoom_slider)
        self._zoom_value = QLabel(f"{zoom:.2f}x")
        self._zoom_value.setFixedWidth(48)
        zoom_row.addWidget(self._zoom_value)
        right.addLayout(zoom_row)

        rot_label = QLabel("Rotate")
        rot_label.setStyleSheet("color: #9a9aa8; font-size: 10px;")
        right.addWidget(rot_label)
        rot_row = QHBoxLayout()
        self._rot_slider = QSlider(Qt.Horizontal)
        self._rot_slider.setRange(-180, 180)
        self._rot_slider.setValue(int(rot))
        self._rot_slider.valueChanged.connect(self._on_rot_slider)
        rot_row.addWidget(self._rot_slider)
        self._rot_value = QLabel(f"{int(rot)}°")
        self._rot_value.setFixedWidth(48)
        rot_row.addWidget(self._rot_value)
        right.addLayout(rot_row)

        right.addStretch(1)
        body.addLayout(right, 1)

        outer.addLayout(body)
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


class _PoseSection(QWidget):
    """Toon pose picker, 2-state. Page 0 = grid of 13 pose tiles. Page 1
    = adjust view (drag + sliders + nudge). The user enters page 1 via
    the 'Adjust' button in page 0's header; Back returns to page 0."""

    pose_changed = Signal(str)
    transform_changed = Signal()  # emitted when adjust view writes to transform

    def __init__(self, dna: Optional[str], current_pose: str, parent=None):
        super().__init__(parent)
        self._dna = dna
        self._current_pose = current_pose
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
        header.addWidget(self._adjust_btn)
        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setToolTip("Refresh pose thumbnails")
        self._refresh_btn.setFixedWidth(32)
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
            grid.addWidget(tile, idx // 4, idx % 4)
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

    def click_adjust(self) -> None:
        if not self._dna:
            return
        if self._adjust_view is None:
            self._adjust_view = _PoseAdjustView(initial=self._transform)
            # Push current pose pixmap into the preview if we have one.
            for t in self._tiles:
                if t.pose == self._current_pose and t.has_pixmap():
                    self._adjust_view.set_pixmap(t._pixmap)
                    break
            self._adjust_view.transform_changed.connect(self._on_adjust_changed)
            self._adjust_view.back_requested.connect(self.click_back)
            self._stack.addWidget(self._adjust_view)
            self._header_stack.addWidget(self._build_adjust_header())
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
                t.set_pixmap(pixmap)
                if pose == self._current_pose and self._adjust_view is not None:
                    self._adjust_view.set_pixmap(pixmap)
                break

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

    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        outer.addWidget(self._label("Color"))
        self._color_row = _SwatchRow(current.get("color"))
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

        self._grad_start = _SwatchRow(
            (current.get("gradient") or {}).get("start")
        )
        self._grad_end = _SwatchRow(
            (current.get("gradient") or {}).get("end")
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
        self._pat_color_row = _SwatchRow(
            (current.get("pattern") or {}).get("color")
        )
        self._pat_color_row.color_picked.connect(lambda _: self._emit_pattern())
        outer.addWidget(self._pat_color_row)

        outer.addWidget(self._label("Outline"))
        outline_dict = current.get("outline") if isinstance(current.get("outline"), dict) else {}
        self._outline_color_row = _SwatchRow(outline_dict.get("color"))
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


class ToonCustomizationDialog(QDialog):
    customization_changed = Signal()

    def __init__(
        self,
        game: str,
        toon_name: str,
        manager,
        skin_color: Optional[QColor] = None,
        auto_stem: Optional[str] = None,
        dna: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._manager = manager
        self._skin = skin_color
        self._auto_stem = auto_stem
        self._dna = dna
        self._draft: dict = dict(manager.get(game, toon_name))
        self._sections: dict[str, QWidget] = {}

        self.setWindowTitle(f"Customize {toon_name}")
        self.setMinimumWidth(720)
        self.setMinimumHeight(520)
        self._build_ui()
        self.resize(760, 560)

    # -- Public test API -------------------------------------------------------

    def section_names(self) -> list[str]:
        return list(self._sections.keys())

    def section(self, name: str) -> QWidget:
        return self._sections[name]

    def draft(self) -> dict:
        return dict(self._draft)

    def set_icon_stem(self, stem: Optional[str]) -> None:
        if self._game != "cc":
            return
        if "Icon" not in self._sections:
            return
        grid: RaceIconGridWidget = self._sections["Icon"]
        if stem is None:
            # Best-effort: nothing to call to "unselect" the grid, so we just
            # update the draft. The dialog tracks the unset state and the
            # grid will visually fall back to the auto-marked tile.
            self._draft.pop("icon_stem", None)
            self._preview.set_draft(self._draft)
            return
        grid.select_stem(stem)
        self._on_icon_stem(stem)

    def set_accent(self, hex_: Optional[str]) -> None:
        accent_section: _SimpleColorSection = self._sections["Accent"]
        accent_section.set_current(hex_)
        self._on_accent_changed(hex_)

    def set_body(self, hex_: Optional[str]) -> None:
        body_section: _SimpleColorSection = self._sections["Body"]
        body_section.set_current(hex_)
        self._on_body_changed(hex_)

    def set_pose(self, pose: str) -> None:
        """Public test API: programmatically pick a pose."""
        from utils.rendition_poses import POSE_NAMES
        if pose not in POSE_NAMES:
            return
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            # Force the section to think the click is fresh by bypassing its
            # short-circuit when pose == current_pose.
            if pose == sec._current_pose:
                # Default behaviour: if already selected, just rewrite draft
                # explicitly (the spec test exercises a back-to-default flow).
                self._on_pose_changed(pose)
                return
            sec._on_tile_clicked(pose)
        else:
            self._on_pose_changed(pose)

    # -- Portrait setters for tests --------------------------------------------

    def set_portrait_color(self, hex_: Optional[str]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_color(hex_)
        self._on_portrait_color(hex_)

    def set_portrait_gradient(self, grad: Optional[dict]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_gradient(grad)
        self._on_portrait_gradient(grad)

    def set_portrait_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_pattern(name, color)
        self._on_portrait_pattern(name, color)

    def set_circle_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_circle_outline(hex_, width_key)

    def reset_all(self) -> None:
        self._draft = {}
        for name, w in self._sections.items():
            if isinstance(w, _SimpleColorSection):
                w.set_current(None)
            elif isinstance(w, _PortraitSection):
                w.set_color(None)
                w.set_gradient(None)
                w.set_pattern(None, None)
            elif isinstance(w, _PoseSection):
                for t in w.tiles():
                    t.set_selected(t.pose == "portrait")
                w._current_pose = "portrait"
            # RaceIconGridWidget keeps its visual selection; that's fine,
            # the draft no longer references it so save will skip it.
        self._preview.set_draft(self._draft)

    def accept_save(self) -> None:
        self._manager.set(self._game, self._toon_name, self._draft)
        self.customization_changed.emit()
        self.accept()

    # -- UI build --------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # Live preview at the top
        self._preview = CardPreviewWidget(
            self._game, self._toon_name, self._draft, dna=self._dna,
        )
        preview_box = QVBoxLayout()
        preview_box.setContentsMargins(0, 0, 0, 0)
        preview_box.addWidget(self._preview, alignment=Qt.AlignHCenter)
        outer.addLayout(preview_box)

        # Body row: sidebar + stack
        body_row = QHBoxLayout()
        body_row.setSpacing(8)

        self._nav = QListWidget()
        self._nav.setFixedWidth(110)
        self._nav.setStyleSheet(
            "QListWidget { background: #252939; border: 1px solid #3a3f55; }"
            "QListWidget::item { padding: 6px 10px; color: #9a9aa8; }"
            "QListWidget::item:selected { background: #2a2f44; color: #e8e8f0; "
            "border-left: 3px solid #4a7cff; }"
        )
        self._stack = QStackedWidget()

        # Icon (CC only)
        if self._game == "cc":
            skin = self._skin or QColor("#d9a04e")
            grid = RaceIconGridWidget(
                skin_color=skin,
                selected_stem=self._draft.get("icon_stem"),
                auto_stem=self._auto_stem,
            )
            grid.selection_changed.connect(self._on_icon_stem)
            self._add_section("Icon", grid)

        # Toon section (TTR only, first in sidebar for TTR)
        if self._game == "ttr":
            from utils.toon_customization_resolve import (
                resolve_pose, resolve_portrait_transform,
            )
            current_pose = resolve_pose(self._draft, "portrait")
            pose_section = _PoseSection(self._dna, current_pose)
            pose_section.pose_changed.connect(self._on_pose_changed)
            pose_section.transform_changed.connect(self._on_transform_changed)
            initial_transform = resolve_portrait_transform(self._draft)
            pose_section.set_transform_from_draft(initial_transform)
            self._add_section("Toon", pose_section)

        # Portrait
        portrait_section = _PortraitSection(self._draft.get("portrait") or {})
        portrait_section.color_changed.connect(self._on_portrait_color)
        portrait_section.gradient_changed.connect(self._on_portrait_gradient)
        portrait_section.pattern_changed.connect(self._on_portrait_pattern)
        portrait_section.circle_outline_changed.connect(self._on_circle_outline)
        self._add_section("Portrait", portrait_section)

        # Accent
        accent_section = _SimpleColorSection(
            "Accent (stripe + chip)", self._draft.get("accent")
        )
        accent_section.color_changed.connect(self._on_accent_changed)
        self._add_section("Accent", accent_section)

        # Body
        body_section = _SimpleColorSection(
            "Body tint", self._draft.get("body")
        )
        body_section.color_changed.connect(self._on_body_changed)
        self._add_section("Body", body_section)

        body_row.addWidget(self._nav)
        body_row.addWidget(self._stack, 1)
        outer.addLayout(body_row, 1)

        # Footer
        footer = QHBoxLayout()
        reset = QPushButton("Reset all")
        reset.clicked.connect(self.reset_all)
        footer.addWidget(reset)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept_save)
        footer.addWidget(save)
        outer.addLayout(footer)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _add_section(self, name: str, widget: QWidget) -> None:
        self._sections[name] = widget
        QListWidgetItem(name, self._nav)
        self._stack.addWidget(widget)

    # -- Field handlers --------------------------------------------------------

    def _on_icon_stem(self, stem: str) -> None:
        if stem:
            self._draft["icon_stem"] = stem
        else:
            self._draft.pop("icon_stem", None)
        self._preview.set_draft(self._draft)

    def _on_accent_changed(self, hex_: Optional[str]) -> None:
        if hex_ is None:
            self._draft.pop("accent", None)
        else:
            self._draft["accent"] = hex_
        self._preview.set_draft(self._draft)

    def _on_body_changed(self, hex_: Optional[str]) -> None:
        if hex_ is None:
            self._draft.pop("body", None)
        else:
            self._draft["body"] = hex_
        self._preview.set_draft(self._draft)

    def _on_pose_changed(self, pose: str) -> None:
        if pose == "portrait":
            # Default - don't pollute the saved entry with the default.
            self._draft.pop("pose", None)
        else:
            self._draft["pose"] = pose
        self._preview.set_draft(self._draft)

    def _on_transform_changed(self) -> None:
        """The Toon section's adjust view changed the transform. Write
        into _draft["portrait"]["transform"]; omit the sub-object when
        at defaults so the saved entry stays minimal."""
        sec = self._sections["Toon"]
        zoom, off_x, off_y, rot = sec.transform()
        portrait = self._draft.setdefault("portrait", {})
        if (
            abs(zoom - 1.0) < 1e-6
            and abs(off_x) < 1e-6
            and abs(off_y) < 1e-6
            and abs(rot) < 1e-6
        ):
            portrait.pop("transform", None)
        else:
            portrait["transform"] = {
                "zoom": zoom,
                "offset_x": off_x,
                "offset_y": off_y,
                "rotate": rot,
            }
        if not self._draft.get("portrait"):
            self._draft.pop("portrait", None)
        self._preview.set_draft(self._draft)

    # -- Portrait field handlers -----------------------------------------------

    def _portrait_subdict(self) -> dict:
        return self._draft.setdefault("portrait", {})

    def _prune_portrait(self) -> None:
        if not self._draft.get("portrait"):
            self._draft.pop("portrait", None)

    def _on_portrait_color(self, hex_: Optional[str]) -> None:
        sub = self._portrait_subdict()
        if hex_ is None:
            sub.pop("color", None)
        else:
            sub["color"] = hex_
        self._prune_portrait()
        self._preview.set_draft(self._draft)

    def _on_portrait_gradient(self, grad: Optional[dict]) -> None:
        sub = self._portrait_subdict()
        if grad is None:
            sub.pop("gradient", None)
        else:
            sub["gradient"] = dict(grad)
        self._prune_portrait()
        self._preview.set_draft(self._draft)

    def _on_portrait_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        sub = self._portrait_subdict()
        if name is None:
            sub.pop("pattern", None)
        else:
            sub["pattern"] = {"name": name, "color": color or "#ffffff"}
        self._prune_portrait()
        self._preview.set_draft(self._draft)

    def _on_circle_outline(
        self, hex_: Optional[str], width_key: str,
    ) -> None:
        sub = self._portrait_subdict()
        if hex_ is None:
            sub.pop("outline", None)
        else:
            sub["outline"] = {"color": hex_, "width": width_key}
        self._prune_portrait()
        self._preview.set_draft(self._draft)
