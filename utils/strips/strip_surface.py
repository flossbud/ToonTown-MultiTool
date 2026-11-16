"""The top-level window that carries one strip over one game window.

Translucent, frameless, never focused, click-through outside the strip's
blocks. It never chases its game window: the follower tells it where to be
once the window has come to rest, and conceals it the moment the window
moves. Concealing is opacity 0 with an empty input region, not an unmap: a
remap would drop the tie to the game window and land on top of the stack.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

from utils import ui_scale
from utils.overlay.backend import OverlayBackend, get_overlay_backend
from utils.overlay.region import controls_region
from utils.strips.attach import AttachStrategy, pick_attach_strategy
from utils.strips.model import StripModel
from utils.strips.strip_widget import StripWidget

# The row's top edge sits this far inside the top of the client area.
ANCHOR_INSET = 10.0


def strip_scale(environ=os.environ) -> float:
    """What to multiply strip metrics by so a strip is true-size on the game
    window: the inverse of the UI scale the app shrank itself by."""
    try:
        active = float(environ.get(ui_scale.ENV_ACTIVE, "") or 1.0)
    except ValueError:
        return 1.0
    return 1.0 / active if 0.3 <= active <= 3.0 else 1.0


def strip_origin(client: QRect, row: QSize, row_offset, scale: float) -> QPoint:
    """Top-left of the surface so the ROW is centred on the client area with
    its top edge ANCHOR_INSET inside it. All Qt logical px."""
    x = client.x() + (client.width() - row.width()) / 2.0 - row_offset.x()
    y = client.y() + ANCHOR_INSET * scale - row_offset.y()
    return QPoint(int(round(x)), int(round(y)))


class StripSurface(QWidget):
    # For whatever hangs off a strip (counters, menus): it is on show or not,
    # and it has moved or changed size.
    presentation_changed = Signal(bool)
    geometry_applied = Signal()

    # Read by the macOS backend when it picks a window level: anything that
    # is not the cluster's type gets the floating panel level.
    WM_WINDOW_TYPE = "strip"

    def __init__(self, strategy: AttachStrategy | None = None,
                 backend: OverlayBackend | None = None,
                 scale: float | None = None) -> None:
        super().__init__(None)       # parentless: its own top-level window
        self._strategy = strategy if strategy is not None else pick_attach_strategy()
        self._backend = backend if backend is not None else get_overlay_backend()
        self.setWindowFlags(self._strategy.window_flags())
        self.setWindowTitle("TTMT strip")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
        self.setFocusPolicy(Qt.NoFocus)

        self.strip = StripWidget(self)
        self.strip.move(0, 0)
        self.strip.set_scale(strip_scale() if scale is None else scale)

        self._game_wid: str | None = None
        self._client: tuple | None = None      # native client rect, if placed
        self._prepared = False
        self._attached = False                 # tied to the game, this map
        self._concealed = True                 # the follower's wish
        self._covered = False                  # gate: nothing may show
        self._visible: QRegion | None = None   # gate: strip-local mask
        self._shown = False
        self.resize(self.strip.sizeHint())

    # -- what it shows ------------------------------------------------------

    def set_model(self, model: StripModel) -> None:
        current = self.strip.model()
        if model == current and model.portrait is current.portrait:
            return                 # nothing to repaint, resize or re-shape
        self.strip.set_model(model)
        self._fit()

    def set_style(self, name: str) -> None:
        self.strip.set_style(name)
        self._fit()

    def _fit(self) -> None:
        """The strip changed size: keep it centred where it was placed."""
        if self._client is not None:
            self._apply_geometry()
        elif self.size() != self.strip.size():
            self.resize(self.strip.size())
        self._present()

    # -- where it is --------------------------------------------------------

    def game_window(self) -> str | None:
        return self._game_wid

    def set_game_window(self, wid: str | None) -> None:
        wid = str(wid) if wid else None
        if wid == self._game_wid:
            return
        self._game_wid = wid
        if wid is not None and self._attached:
            self._strategy.attach(self, self._backend, wid)

    def is_presented(self) -> bool:
        """True while the strip is really on show (not concealed, not
        covered, tied to its window)."""
        return self._shown

    def place(self, client_native) -> None:
        """Put the strip on a game window that has come to rest. `client`
        is its client rectangle in the platform's native units."""
        self._client = tuple(client_native)
        self._apply_geometry()
        self._concealed = False
        if not self.isVisible():
            self._map()
        else:
            self._present()

    def conceal(self) -> None:
        """The window is moving, minimized or gone: show nothing, take no
        input, stay mapped."""
        self._concealed = True
        self._present()

    def client_logical(self) -> QRect | None:
        if self._client is None:
            return None
        x, y, w, h = self._client
        left, top = self._strategy.to_logical(x, y)
        right, bottom = self._strategy.to_logical(x + w, y + h)
        return QRect(left, top, right - left, bottom - top)

    def _apply_geometry(self) -> None:
        client = self.client_logical()
        if client is None:
            return
        k = self.strip.scale()
        # Client width in strip design px decides the narrow collapse.
        self.strip.set_client_width(client.width() / k)
        size = self.strip.sizeHint()
        # The offset stays fractional: rounding it first would shift a
        # scaled strip by a pixel.
        origin = strip_origin(client, self.strip.row_size(),
                              self.strip.row_offset(), k)
        target = QRect(origin, size)
        if target != self.geometry():
            self.setGeometry(target)
        self.geometry_applied.emit()

    @property
    def strategy(self) -> AttachStrategy:
        return self._strategy

    @property
    def backend(self) -> OverlayBackend:
        return self._backend

    # -- mapping and the tie to the game window -----------------------------

    def _map(self) -> None:
        if not self._prepared:
            self._prepared = True
            self.winId()             # native handle, still unmapped
            try:
                self._strategy.prepare(self, self._backend)
            except Exception:
                pass
        # Staged: invisible until the first paint has happened and the tie
        # is in place, so it can never flash over a window covering the
        # game, and a late first paint never shows as black bands.
        self.setWindowOpacity(0.0)
        self.show()

    def paintEvent(self, _event) -> None:
        # Paints nothing itself; the first paint after a map is the proof
        # the window is really mapped, so the tie can land.
        if not self._attached:
            QTimer.singleShot(0, self._after_map)

    def _after_map(self) -> None:
        if self._attached or not self.isVisible():
            return
        ok = True
        if self._game_wid is not None:
            try:
                ok = bool(self._strategy.attach(self, self._backend, self._game_wid))
            except Exception:
                ok = False
        if not ok:
            print(f"[Strips] attach failed for window {self._game_wid}; "
                  "strip stays hidden")
            return
        self._attached = True
        # A window manager may have placed the fresh window itself.
        self._apply_geometry()
        self._present()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._shown:
            self._shown = False
            self.presentation_changed.emit(False)
        if event.spontaneous():
            # Unmapped by the window manager (minimized along with its game
            # window). Qt did not touch the tie, and no paint is guaranteed
            # on the way back, so the spontaneous show re-asserts it.
            return
        # Our own unmap drops the tie (Qt rewrites the property on the next
        # show): the next map must stage and attach again.
        self._attached = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if event.spontaneous() and self._attached:
            QTimer.singleShot(0, self._reassert)

    def _reassert(self) -> None:
        """Mapped again by the window manager: restack over the game window
        and put the presentation back."""
        if not self.isVisible():
            return
        if self._game_wid is not None:
            try:
                self._strategy.attach(self, self._backend, self._game_wid)
            except Exception:
                pass
        self._present()

    def closeEvent(self, event) -> None:
        # Only the follower destroys a strip; a stray window-manager close
        # must not.
        if event.spontaneous():
            event.ignore()
            return
        event.accept()

    # -- gate (platforms that compute visibility) ---------------------------

    def set_visible_region(self, region: QRegion | None) -> None:
        """Strip-local region that may show. None lifts the mask; an empty
        region means the game window is fully covered."""
        if region is None or region == QRegion(self.rect()):
            covered, visible = False, None
        elif region.isEmpty():
            # Never setMask(empty): on cocoa that means "no mask".
            covered, visible = True, None
        else:
            covered, visible = False, QRegion(region)
        if covered == self._covered and visible == self._visible:
            return
        self._covered, self._visible = covered, visible
        if visible is None:
            self.clearMask()
        else:
            self.setMask(visible)
        self._present()

    # -- presentation -------------------------------------------------------

    def input_region(self) -> QRegion:
        """Where the strip takes the pointer, in the units the backend
        wants: the blocks, less whatever the gate masks off."""
        ratio = self._strategy.region_ratio(self)
        region = controls_region(self.strip.input_rects(), 1.0, ratio)
        if self._visible is not None:
            mask = QRegion()
            for r in self._visible:
                mask = mask.united(QRegion(
                    round(r.x() * ratio), round(r.y() * ratio),
                    round(r.width() * ratio), round(r.height() * ratio)))
            region = region.intersected(mask)
        return region

    def _present(self) -> None:
        shown = (self._attached and not self._concealed and not self._covered
                 and self.isVisible())
        changed, self._shown = shown != self._shown, shown
        if changed:
            self.presentation_changed.emit(shown)
        if not self.isVisible():
            return
        try:
            self._backend.apply_input_region(
                self, self.input_region() if shown else QRegion())
        except Exception:
            pass
        self.setWindowOpacity(1.0 if shown else 0.0)
