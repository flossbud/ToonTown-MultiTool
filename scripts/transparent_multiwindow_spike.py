"""Phase-0 spike for the MULTI-WINDOW transparent mode. Operator-run, not a unit test.

Validates on the operator's WM (KWin/XWayland) the load-bearing assumptions of the replanned
architecture, BEFORE we build production on it:
  1. Each card + the emblem is its OWN frameless / translucent / always-on-top / NON-ACTIVATING
     top-level window (no Qt parent). They must stay above a focused game and NEVER steal the
     game's keyboard focus.
  2. Per-window X11 ShapeInput: the concave 'bite' (and everything outside the card body) is
     click-through to the game; the card BODY is solid (clicks land on it).
  3. Z-order: the emblem window stays above the 4 card windows.
  4. Scroll-on-emblem rescales the whole group by RECOMPUTING each card's size (no transform) and
     keeps the mini-pinwheel aligned + crisp.

Run:   TTMT_NO_VENV_REEXEC=1 ./venv/bin/python scripts/transparent_multiwindow_spike.py
Mouse: scroll on the emblem = resize the group; drag the emblem = move the group;
       RIGHT-CLICK the emblem = quit.
Auto-closes after TTMT_SPIKE_TIMEOUT seconds (default 120). Log -> ~/ttmt_multiwindow_spike.log
"""
from __future__ import annotations
import os
import sys
import pathlib

from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QPixmap, QTransform, QFont,
)
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from utils.overlay.scale import step_scale  # noqa: E402
from utils.overlay.region import build_input_region  # noqa: E402
from utils.overlay.x11_backend import X11OverlayBackend  # noqa: E402

LOG = os.path.expanduser("~/ttmt_multiwindow_spike.log")


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


# Base metrics at scale 1.0 (mirror the real card constants).
CARD_W, CARD_H = 300, 232
CARD_RADIUS, CUTOUT_R = 20, 96
EMBLEM = 156
GAP = 24  # gap between a card's inner corner and the group center

# cutout corner -> (right?, bottom?) within the card rect
_CORNER = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}

_BACKEND = X11OverlayBackend()


def set_skip_taskbar(widget) -> None:
    """EWMH: hide an independent overlay window from the taskbar + pager. `Qt.Tool` alone does
    NOT do this for a parentless top-level on KWin, so set _NET_WM_STATE_SKIP_TASKBAR explicitly."""
    d = getattr(_BACKEND, "_display", None)
    if d is None:
        return
    try:
        from Xlib import X
        from Xlib.protocol import event as xevent
        win = d.create_resource_object("window", int(widget.winId()))
        a = d.intern_atom
        ev = xevent.ClientMessage(
            window=win, client_type=a("_NET_WM_STATE"),
            data=(32, [1, a("_NET_WM_STATE_SKIP_TASKBAR"), a("_NET_WM_STATE_SKIP_PAGER"), 1, 0]))
        d.screen().root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.flush()
    except Exception as exc:
        log(f"skip_taskbar FAILED: {exc!r}")


def card_body_path(w: float, h: float, cutout: str, radius: float, cutout_r: float) -> QPainterPath:
    """Rounded rect minus a concave bite at the `cutout` corner (matches the real card body)."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    cx = w if _CORNER[cutout][0] else 0
    cy = h if _CORNER[cutout][1] else 0
    bite = QPainterPath()
    bite.addEllipse(QPointF(cx, cy), cutout_r, cutout_r)
    return body.subtracted(bite)


class Surface(QWidget):
    """A non-activating, always-on-top, translucent, independent top-level overlay window."""

    def __init__(self, kind: str, cutout: str | None = None, label: str = ""):
        super().__init__(None)  # NO Qt parent -> independent top-level
        self.kind = kind
        self.cutout = cutout
        self.label = label
        self._scale = 1.0
        self._taskbar_skipped = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        try:
            self.setAttribute(Qt.WA_X11DoNotAcceptFocus, True)
        except Exception:
            pass

    def _body_path(self) -> QPainterPath:
        w, h = self.width(), self.height()
        if self.kind == "card":
            return card_body_path(w, h, self.cutout, CARD_RADIUS * self._scale, CUTOUT_R * self._scale)
        p = QPainterPath()
        p.addEllipse(QRectF(0, 0, w, h))
        return p

    def set_scale_and_size(self, scale: float) -> None:
        self._scale = scale
        if self.kind == "card":
            self.setFixedSize(int(CARD_W * scale), int(CARD_H * scale))
        else:
            self.setFixedSize(int(EMBLEM * scale), int(EMBLEM * scale))

    def reshape(self) -> None:
        """Input-shape this window to its body path so the bite/outside is click-through."""
        region = build_input_region([self._body_path()], QPainterPath(), QTransform())
        try:
            _BACKEND.apply_input_region(self, region)
        except Exception as exc:
            log(f"shape FAILED ({self.kind}/{self.cutout}): {exc!r}")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self._scale
        if self.kind == "card":
            p.setBrush(QColor("#cfe3f5"))
            p.setPen(QPen(QColor("#2b6cb0"), max(2, int(5 * s))))
            p.drawPath(self._body_path())
            p.setBrush(QColor("#1f2630"))
            p.setPen(QPen(QColor("#2b6cb0"), max(2, int(3 * s))))
            r = int(70 * s)
            p.drawEllipse(int(16 * s), int(46 * s), r, r)
            f = QFont()
            f.setPointSizeF(max(6.0, 13 * s))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#15202b"))
            p.drawText(int(16 * s), int(34 * s), self.label)
        else:
            p.setBrush(QColor("#93aebd"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self.rect())
            icon = pathlib.Path(__file__).resolve().parent.parent / "assets" / "multitool.png"
            if icon.exists():
                pm = QPixmap(str(icon)).scaled(
                    int(self.width() * 0.82), int(self.height() * 0.82),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap((self.width() - pm.width()) // 2, (self.height() - pm.height()) // 2, pm)
        p.end()


class EmblemSurface(Surface):
    """The emblem window carries the group's mouse controls (works without keyboard focus)."""

    def __init__(self, group):
        super().__init__("emblem")
        self._group = group
        self._press = None

    def wheelEvent(self, event):
        self._group.rescale(1 if event.angleDelta().y() > 0 else -1)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            QApplication.instance().quit()
            return
        self._press = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._press is not None:
            now = event.globalPosition().toPoint()
            self._group.move_by(now.x() - self._press.x(), now.y() - self._press.y())
            self._press = now

    def mouseReleaseEvent(self, event):
        self._press = None


class Group:
    def __init__(self, app):
        self._scale = 1.0
        # slot -> cutout corner facing the group center
        self.cards = [
            Surface("card", "br", "Toon 1"),  # top-left quadrant
            Surface("card", "bl", "Toon 2"),  # top-right
            Surface("card", "tr", "Toon 3"),  # bottom-left
            Surface("card", "tl", "Toon 4"),  # bottom-right
        ]
        self.emblem = EmblemSurface(self)
        scr = app.primaryScreen().geometry()
        self.cx, self.cy = scr.center().x(), scr.center().y()
        self.apply()

    def _all(self):
        return self.cards + [self.emblem]

    def apply(self):
        s = self._scale
        cw, ch = int(CARD_W * s), int(CARD_H * s)
        em = int(EMBLEM * s)
        g = int(GAP * s)
        cx, cy = self.cx, self.cy
        for surf in self._all():
            surf.set_scale_and_size(s)
        positions = [
            (cx - g - cw, cy - g - ch),  # card 0 TL, bite br -> center
            (cx + g, cy - g - ch),       # card 1 TR, bite bl
            (cx - g - cw, cy + g),       # card 2 BL, bite tr
            (cx + g, cy + g),            # card 3 BR, bite tl
        ]
        for card, (x, y) in zip(self.cards, positions):
            card.move(x, y)
        self.emblem.move(cx - em // 2, cy - em // 2)
        for surf in self._all():
            if not surf.isVisible():
                surf.show()
            if not surf._taskbar_skipped:
                set_skip_taskbar(surf)
                surf._taskbar_skipped = True
            surf.reshape()
        self.emblem.raise_()  # emblem above cards
        log(f"applied scale={s:.2f} center=({cx},{cy})")

    def rescale(self, notches):
        self._scale = step_scale(self._scale, notches)
        self.apply()

    def move_by(self, dx, dy):
        self.cx += dx
        self.cy += dy
        self.apply()


def main():
    log(f"=== multiwindow spike start: exe={sys.executable} backend_avail={_BACKEND.is_available()} ===")
    app = QApplication(sys.argv)
    group = Group(app)
    log("spike up: scroll emblem=resize, drag emblem=move, RIGHT-CLICK emblem=quit. "
        "Test: above a focused game? bite click-through? body solid? no keyboard-focus theft?")
    timeout = int(os.environ.get("TTMT_SPIKE_TIMEOUT", "120"))
    if timeout > 0:
        QTimer.singleShot(timeout * 1000, app.quit)
        log(f"auto-close in {timeout}s")
    app.exec()


if __name__ == "__main__":
    main()
