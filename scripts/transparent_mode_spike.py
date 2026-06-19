"""Phase-0 spike for Transparent Mode. Operator-run, not a unit test.

Validates (1) QGraphicsProxyWidget scaling crispness + interaction fidelity and
(2) X11 ShapeInput click-through, together, in one frameless translucent always-on-top
window. Run on the live desktop with two game windows behind it.

Run:  TTMT_NO_VENV_REEXEC=1 python scripts/transparent_mode_spike.py
Keys: '+'/'-' scale, 'r' reset to 100%, 'q' quit. Log -> ~/ttmt_transparent_spike.log
"""
from __future__ import annotations
import os, sys, pathlib

from PySide6.QtCore import Qt, QRectF, QTimer, QPointF
from PySide6.QtGui import QPainterPath, QTransform, QPixmap
from PySide6.QtWidgets import (
    QApplication, QGraphicsScene, QGraphicsView, QWidget, QFrame, QLabel,
    QPushButton, QSlider, QHBoxLayout, QVBoxLayout, QGridLayout,
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from utils.overlay.scale import step_scale  # noqa: E402
from utils.overlay.region import build_input_region  # noqa: E402

LOG = os.path.expanduser("~/ttmt_transparent_spike.log")

def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(msg + "\n")
    print(msg)

def _stub_card(name: str) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet("#card{background:#cfe3f5;border:5px solid #2b6cb0;border-radius:20px;}")
    v = QVBoxLayout(card); v.setContentsMargins(12, 12, 12, 12)
    v.addWidget(QLabel(name))
    row = QHBoxLayout()
    row.addWidget(QPushButton("On"))
    row.addWidget(QPushButton("KA"))
    row.addWidget(QPushButton("Chat"))
    v.addLayout(row)
    v.addWidget(QSlider(Qt.Horizontal))
    stepper = QFrame(); sh = QHBoxLayout(stepper)
    sh.addWidget(QPushButton("<")); sh.addWidget(QLabel("Keyset 2")); sh.addWidget(QPushButton(">"))
    v.addWidget(stepper)
    card.setFixedSize(330, 232)
    return card

def _cluster() -> QWidget:
    root = QWidget()
    # Embedded via QGraphicsProxyWidget the root is treated as a top-level widget and
    # paints its dark palette background in the gaps -> make it translucent. The cards
    # keep their own light-blue (#card) background; only the gaps go transparent.
    root.setAttribute(Qt.WA_TranslucentBackground, True)
    grid = QGridLayout(root); grid.setSpacing(40)
    names = ["Flossbud", "Frutiger Aero", "Hector Pep.", "Gifted Str."]
    for i, n in enumerate(names):
        grid.addWidget(_stub_card(n), i // 2, i % 2)
    emblem = QLabel(root)
    icon = pathlib.Path(__file__).resolve().parent.parent / "assets" / "multitool.png"
    if icon.exists():
        emblem.setPixmap(QPixmap(str(icon)).scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    emblem.setFixedSize(120, 120)
    emblem.setAttribute(Qt.WA_TransparentForMouseEvents)
    return root

class SpikeView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scale = 1.0
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        scene = QGraphicsScene(self)
        scene.setBackgroundBrush(Qt.transparent)
        self._proxy = scene.addWidget(_cluster())
        self.setScene(scene)
        # A QGraphicsView paints through a viewport widget; the dark-palette viewport
        # background is what showed as the opaque navy rectangle. Make the viewport
        # transparent too. This same fix belongs in the production ClusterHost.
        self.viewport().setAutoFillBackground(False)
        self.viewport().setStyleSheet("background: transparent;")
        self._apply_scale()

    def _apply_scale(self) -> None:
        self.resetTransform()
        self.scale(self._scale, self._scale)
        br = self._proxy.boundingRect()
        self.setSceneRect(br)
        self.setFixedSize(int(br.width() * self._scale) + 2, int(br.height() * self._scale) + 2)
        self._apply_shape()

    def _apply_shape(self) -> None:
        # Build the QRegion from stub card rects + emblem, scaled, then push to X11 ShapeInput.
        # NOTE (spike): confirm the exact python-xlib shape method names on this box; tune live.
        try:
            from Xlib import display as xdisplay, X
            from Xlib.ext import shape
            transform = QTransform().scale(self._scale, self._scale)
            card_paths = []
            for child in self._proxy.widget().findChildren(QFrame, "card"):
                geo = child.geometry()
                p = QPainterPath(); p.addRoundedRect(QRectF(geo), 20, 20)
                card_paths.append(p)
            region = build_input_region(card_paths, QPainterPath(), transform)
            rects = [(r.x(), r.y(), r.width(), r.height()) for r in region]
            d = xdisplay.Display()
            w = d.create_resource_object("window", int(self.winId()))
            w.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, rects)
            d.flush()
            log(f"shape applied: scale={self._scale:.2f} rects={len(rects)}")
        except Exception as exc:  # spike: surface, don't crash
            log(f"shape FAILED (tune needed): {exc!r}")

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self._scale = step_scale(self._scale, 1); self._apply_scale()
        elif key == Qt.Key_Minus:
            self._scale = step_scale(self._scale, -1); self._apply_scale()
        elif key == Qt.Key_R:
            self._scale = 1.0; self._apply_scale()
        elif key in (Qt.Key_Q, Qt.Key_Escape):
            self.close()

def main() -> None:
    log(f"=== spike start: frozen={getattr(sys,'frozen',False)} exe={sys.executable} ===")
    app = QApplication(sys.argv)
    view = SpikeView()
    view.show()
    timeout = int(os.environ.get("TTMT_SPIKE_TIMEOUT", "120"))
    if timeout > 0:
        QTimer.singleShot(timeout * 1000, view.close)  # safety auto-close; never gets stuck
        log(f"auto-close in {timeout}s; press q or Esc to quit early")
    log("spike window shown; test click-through in gaps, interactions on cards, crispness at +/-")
    app.exec()

if __name__ == "__main__":
    main()
