"""Rung-A probe (Float UI taskbar spec 2026-07-02): can the CLUSTER window be
the taskbar entry directly?

Maps a window with the cluster's exact WM identity - managed, frameless,
keep-above, DOCK type, focus-refusing - but WITHOUT the SKIP_TASKBAR /
SKIP_PAGER hints, then asks the operator what Plasma does with it.

Run ON THE REAL SESSION (never offscreen):

    python scripts/probes/probe_a_dock_taskbar.py

Record the answers in the HANDOFF. Expected from theory: Plasma's task manager
and KWin's TabBox both filter DOCK windows, so NO on all three questions ->
rung A is DISPROVEN empirically and rung B (representative window) proceeds.
Theory is not evidence: run it.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")   # X window identity, like the app

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

LIFETIME_MS = 120_000


def premap_hints(widget) -> None:
    """The cluster's pre-map identity minus the skip hints: DOCK type + ABOVE.
    Mirrors x11_backend.set_initial_state, which writes these on the cluster
    (plus the skip hints this probe deliberately omits)."""
    from Xlib import X, Xatom
    from Xlib import display as xdisplay
    d = xdisplay.Display()
    win = d.create_resource_object("window", int(widget.winId()))
    a = d.intern_atom
    win.change_property(a("_NET_WM_STATE"), Xatom.ATOM, 32,
                        [a("_NET_WM_STATE_ABOVE")], X.PropModeReplace)
    win.change_property(a("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32,
                        [a("_NET_WM_WINDOW_TYPE_DOCK")], X.PropModeReplace)
    d.flush()


def main() -> int:
    app = QApplication(sys.argv)
    w = QWidget(None, Qt.Window | Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    w.setWindowTitle("TTMT probe A - dock in taskbar?")
    lay = QVBoxLayout(w)
    label = QLabel("PROBE A\nDOCK + keep-above, NO skip-taskbar\n"
                   "Check: taskbar entry / hover preview / Alt-Tab")
    label.setAlignment(Qt.AlignCenter)
    lay.addWidget(label)
    w.setStyleSheet("background: #aa00cc; color: white; font-size: 20px;")
    w.resize(420, 240)
    w.move(200, 200)
    premap_hints(w)          # pre-map, mirroring the cluster's discipline
    w.show()
    print("PROBE A up (auto-quits in 120s). Record in the HANDOFF:")
    print("  1) Does the Plasma taskbar show an entry for it?")
    print("  2) If yes: does hovering show a live preview?")
    print("  3) Does Alt-Tab list it?")
    QTimer.singleShot(LIFETIME_MS, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
