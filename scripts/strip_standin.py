"""Plain windows standing in for game windows, for strip attach checks.

    python scripts/strip_standin.py game:100,120,800,600 other:300,200,500,400
    python scripts/strip_standin.py "game1:100,120,800,600:Stand-in window one"

A third field is the window title (default strip-standin-<name>). A title
must not CONTAIN "Toontown Rewritten" or "Corporate Clash": the app finds
game windows by title (by substring on Windows), and a stand-in must never
be mistaken for a game.

Prints `STANDIN <name> <window id>` once each window is up, then
`STANDIN-CLICK <name> <x> <y>` for every mouse press it receives,
`STANDIN-KEY <name> <qt key> <text>` for every key press and
`STANDIN-FOCUS <name> in|out` when it gains or loses focus. Runs until killed.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget


def say(*parts) -> None:
    print(*parts, flush=True)


class StandIn(QWidget):
    def __init__(self, name: str, x: int, y: int, w: int, h: int,
                 title: str = "") -> None:
        super().__init__()
        self._name = name
        self._label = title or name
        self.setWindowTitle(title or f"strip-standin-{name}")
        self.setGeometry(x, y, w, h)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#24303a" if self._name.startswith("game")
                                       else "#5a3d2b"))
        p.setPen(QColor("#ffffff"))
        p.drawText(self.rect(), Qt.AlignCenter, self._label)

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        say("STANDIN-CLICK", self._name, pos.x(), pos.y())

    def keyPressEvent(self, event) -> None:
        say("STANDIN-KEY", self._name, event.key(), event.text() or "-")

    def focusInEvent(self, event) -> None:
        say("STANDIN-FOCUS", self._name, "in")

    def focusOutEvent(self, event) -> None:
        say("STANDIN-FOCUS", self._name, "out")


def main() -> int:
    app = QApplication(sys.argv[:1])
    windows = []
    for spec in sys.argv[1:]:
        name, _, rest = spec.partition(":")
        geo, _, title = rest.partition(":")
        x, y, w, h = (int(v) for v in (geo or "100,100,800,600").split(","))
        win = StandIn(name, x, y, w, h, title)
        win.show()
        windows.append((name, win))
    # Report ids once the windows are really mapped.
    QTimer.singleShot(400, lambda: [say("STANDIN", n, int(w.winId()))
                                    for n, w in windows])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
