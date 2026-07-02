"""Rung-B0 probe (Float UI taskbar spec 2026-07-02): does a taskbar hover
thumbnail still show a window's PAINTED CONTENT when the window is made
imperceptible with _NET_WM_WINDOW_OPACITY=0?

The representative-window design rests on this one mechanism: the compositor
applies window opacity at paint time, while (on X11) taskbar thumbnails bind
the window's redirected pixmap, which still holds the painted pixels. Under a
Wayland session (XWayland window, KWin-internal thumbnail path) the answer may
differ - which is exactly why this is probed BEFORE rung B is built.

Run ON THE REAL SESSION:

    python scripts/probes/probe_b_opacity_thumbnail.py            # opacity 0
    python scripts/probes/probe_b_opacity_thumbnail.py --opaque   # control run

Record the answers in the HANDOFF.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

LIFETIME_MS = 120_000


class ProbeWindow(QWidget):
    """Paints an unmistakable pattern so a thumbnail is easy to judge."""

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ff00aa"))
        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(22)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "PROBE B\nthumbnail content")
        p.drawRect(self.rect().adjusted(6, 6, -6, -6))
        p.end()


def premap_hints(widget) -> None:
    """The representative's identity: keep-below, default NORMAL type (no
    type write), NO skip hints (the whole point is to be listed)."""
    from Xlib import X, Xatom
    from Xlib import display as xdisplay
    d = xdisplay.Display()
    win = d.create_resource_object("window", int(widget.winId()))
    a = d.intern_atom
    win.change_property(a("_NET_WM_STATE"), Xatom.ATOM, 32,
                        [a("_NET_WM_STATE_BELOW")], X.PropModeReplace)
    d.flush()


def set_opacity_zero(widget) -> None:
    from Xlib import X, Xatom
    from Xlib import display as xdisplay
    d = xdisplay.Display()
    win = d.create_resource_object("window", int(widget.winId()))
    win.change_property(d.intern_atom("_NET_WM_WINDOW_OPACITY"),
                        Xatom.CARDINAL, 32, [0], X.PropModeReplace)
    d.flush()


def main() -> int:
    opaque = "--opaque" in sys.argv
    app = QApplication(sys.argv)
    w = ProbeWindow(None, Qt.Window | Qt.FramelessWindowHint)
    w.setWindowTitle("TTMT probe B - opacity-0 thumbnail?")
    w.resize(420, 240)
    w.move(300, 300)
    premap_hints(w)
    if not opaque:
        set_opacity_zero(w)   # pre-map...
    w.show()
    if not opaque:
        # ...and re-asserted post-map in case the WM re-created the frame.
        QTimer.singleShot(200, lambda: set_opacity_zero(w))
    mode = "OPAQUE control" if opaque else "OPACITY 0"
    print(f"PROBE B up ({mode}, auto-quits in 120s). Record in the HANDOFF:")
    print("  1) Is the window invisible on screen (opacity-0 run only)?")
    print("  2) Does the taskbar show an entry?")
    print("  3) Does the hover thumbnail show the MAGENTA pattern?")
    print("  4) Does Alt-Tab list it, with a preview?")
    print("  5) Does the preview's X (close) quit this script?")
    QTimer.singleShot(LIFETIME_MS, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
