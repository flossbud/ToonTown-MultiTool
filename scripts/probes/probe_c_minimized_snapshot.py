"""Rung-C probe (Float UI taskbar, follow-up to probes A/B, 2026-07-02): does a
MINIMIZED window's taskbar thumbnail show its last-painted content?

Probe B disproved the opacity-0 live-thumbnail mechanism (KWin applies window
opacity to the thumbnail too). But the original bug this feature fixes existed
BECAUSE minimized windows keep a cached snapshot thumbnail. If that cache holds
the window's BUFFER (the painted pixels), a representative can live minimized:
taskbar entry + Alt-Tab + invisible on screen + Close-quits all come free, and
the preview is a snapshot refreshed on state changes.

Two runs answer two questions:

    python scripts/probes/probe_c_minimized_snapshot.py             # opaque
    python scripts/probes/probe_c_minimized_snapshot.py --invisible # opacity 0

Opaque run: the window shows for 4 seconds (visible), then minimizes itself.
-> Does the taskbar thumbnail STILL show the magenta pattern after minimize?

Invisible run: same, but the window is opacity-0 while mapped (never seen on
screen). -> If the minimize-cache is the BUFFER, the thumbnail shows the
pattern even though the window was never visible - the ideal refresh
mechanism (map invisibly, repaint, re-minimize, no visual artifacts). If the
cache is the composited (opacity-applied) image, it shows nothing.

Record the answers in the HANDOFF.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

LIFETIME_MS = 120_000
MINIMIZE_AFTER_MS = 4_000


class ProbeWindow(QWidget):
    """Paints an unmistakable pattern so a thumbnail is easy to judge."""

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ff00aa"))
        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(22)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "PROBE C\nminimized snapshot")
        p.drawRect(self.rect().adjusted(6, 6, -6, -6))
        p.end()


def set_opacity_zero(widget) -> None:
    from Xlib import X, Xatom
    from Xlib import display as xdisplay
    d = xdisplay.Display()
    win = d.create_resource_object("window", int(widget.winId()))
    win.change_property(d.intern_atom("_NET_WM_WINDOW_OPACITY"),
                        Xatom.CARDINAL, 32, [0], X.PropModeReplace)
    d.flush()


def main() -> int:
    invisible = "--invisible" in sys.argv
    app = QApplication(sys.argv)
    w = ProbeWindow(None, Qt.Window | Qt.FramelessWindowHint)
    w.setWindowTitle("TTMT probe C - minimized snapshot?")
    w.resize(420, 240)
    w.move(300, 300)
    if invisible:
        set_opacity_zero(w)   # pre-map; never visible on screen
    w.show()
    if invisible:
        QTimer.singleShot(200, lambda: set_opacity_zero(w))
    mode = "OPACITY 0 while mapped" if invisible else "OPAQUE"
    print(f"PROBE C up ({mode}). It minimizes ITSELF in 4 seconds.")
    print("AFTER it minimizes, record in the HANDOFF:")
    print("  1) Does hovering the taskbar entry show the MAGENTA pattern?")
    print("  2) Is it in Alt-Tab, with the pattern in the preview?")
    print("  3) Does the preview's X (close) quit this script?")
    print("  (Do NOT left-click the taskbar entry - that would restore it;")
    print("   that behavior is handled separately in the real feature.)")
    QTimer.singleShot(MINIMIZE_AFTER_MS, w.showMinimized)
    QTimer.singleShot(LIFETIME_MS, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
