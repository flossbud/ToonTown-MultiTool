"""Render every float-strip state offscreen and save PNGs.

A construction check: it shows what the painter draws, not how a strip
behaves on a real desktop. Each state is the real StripWidget mounted in a
parent that paints the handoff's striped stand-in for a game viewport, 10 px
from the top, the way the spec sheet shows it.

    python scripts/strip_render.py OUTDIR [--scale 2] [--fonts DIR]
                                   [--compare SCREENSHOT_DIR]

--scale     device pixel ratio of the renders (default 1, the screenshots' ratio)
--fonts     a folder of extra font files to load (the app does not ship Inter)
--compare   the handoff's screenshots/ folder; adds <style>-compare.png with
            each design crop above our render of the same state
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--fonts", default=None)
    ap.add_argument("--compare", default=None)
    return ap.parse_args(argv)


ARGS = _parse(sys.argv[1:])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt                      # noqa: E402
from PySide6.QtGui import (QColor, QFontDatabase, QImage,          # noqa: E402
                           QPainter)
from PySide6.QtWidgets import QApplication, QWidget                # noqa: E402

from utils.strips import tokens                                    # noqa: E402
from utils.strips.model import StripModel                          # noqa: E402
from utils.strips.strip_widget import MARGIN, StripWidget          # noqa: E402

FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")
HECTOR = StripModel(name="Hector", accent="#e74a4a", species="dog")
MOE = StripModel(name="Moe", accent="#e7894a", species="cat", game="cc")
LINUX = StripModel(name="Linux", accent="#56c856", species="duck")

# name, model, viewport width, and where the same state sits in
# <style>-03-states.png (x, y of its 560 x 96 crop), when it is there.
STATES = [
    ("one-keyset", FLOSSBUD.with_(keysets=(1,)), 560, (28, 107)),
    ("eight-keysets", HECTOR.with_(keysets=tuple(range(1, 9)), active=5,
                                   show_add=False), 560, (588, 107)),
    ("toon-disabled", HECTOR.with_(enabled=False), 560, (28, 248)),
    ("tools-off", LINUX.with_(keep_alive=False, click_sync=False), 560, (588, 248)),
    ("at-rest", FLOSSBUD, 560, (28, 389)),
    ("narrow", LINUX, 320, (588, 546)),
    ("narrow-active-only", HECTOR.with_(keysets=tuple(range(1, 9)), active=5,
                                        show_add=False, home=True), 240, None),
    ("hidden-sets", HECTOR.with_(keysets=(1, 2), hidden_sets=True), 560, (588, 687)),
    ("home", FLOSSBUD.with_(home=True), 560, None),
    ("home-open", FLOSSBUD.with_(home=True, home_open=True), 560, None),
    ("stopped", FLOSSBUD.with_(home=True, running=False), 560, None),
    ("features-off", MOE.with_(keep_alive=None, click_sync=None), 560, None),
    ("long-name", HECTOR.with_(name="Captain Fluffy McSparkle"), 560, None),
]
CROP_H = 96


class Viewport(QWidget):
    """The handoff's stand-in for a game viewport: diagonal stripes."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.setFixedSize(width, CROP_H)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#191b20"))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1c1e24"))
        # repeating-linear-gradient(135deg, a 0 14px, b 14px 28px)
        period = 28 * 2 ** 0.5
        span = self.width() + self.height()
        x = -span
        while x < span:
            p.drawPolygon([QPoint(int(x), 0), QPoint(int(x + period / 2), 0),
                           QPoint(int(x + period / 2 + self.height()), self.height()),
                           QPoint(int(x + self.height()), self.height())])
            x += period
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor("#3a3a3a"))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


def render_state(style: str, model: StripModel, width: int) -> QImage:
    view = Viewport(width)
    strip = StripWidget(view)
    strip.set_style(style)
    strip.set_client_width(width)
    strip.set_model(model)
    row = strip.row_size()
    # Row centred, its top edge 10 px inside the viewport.
    strip.move(int(round((width - row.width()) / 2 - MARGIN)), int(10 - MARGIN))
    view.show()
    QApplication.processEvents()
    dpr = ARGS.scale
    image = QImage(int(round(width * dpr)), int(round(CROP_H * dpr)),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    view.render(image)
    image.setDevicePixelRatio(1.0)
    view.close()
    view.deleteLater()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication([])
    if ARGS.fonts:
        for name in sorted(os.listdir(ARGS.fonts)):
            QFontDatabase.addApplicationFont(os.path.join(ARGS.fonts, name))
    os.makedirs(ARGS.outdir, exist_ok=True)
    dpr = ARGS.scale
    for style in tokens.STYLES:
        images = []
        for name, model, width, _crop in STATES:
            image = render_state(style, model, width)
            image.save(os.path.join(ARGS.outdir, f"{style}-{name}.png"))
            images.append(image)

        cols, gap = 2, 12
        rows = (len(images) + cols - 1) // cols
        sheet = QImage(int((cols * 560 + (cols + 1) * gap) * dpr),
                       int((rows * (CROP_H + gap) + gap) * dpr),
                       QImage.Format_ARGB32_Premultiplied)
        sheet.fill(QColor("#101114"))
        sp = QPainter(sheet)
        for i, image in enumerate(images):
            x = gap + (i % cols) * (560 + gap)
            y = gap + (i // cols) * (CROP_H + gap)
            sp.drawImage(QPoint(int(x * dpr), int(y * dpr)), image)
        sp.end()
        sheet.save(os.path.join(ARGS.outdir, f"{style}-sheet.png"))

        if ARGS.compare:
            design = QImage(os.path.join(ARGS.compare, f"{style}-03-states.png"))
            pairs = [(img, st) for img, st in zip(images, STATES) if st[3]]
            if design.isNull() or not pairs:
                print(f"no design screenshot for {style} in {ARGS.compare}")
                continue
            # The screenshots are 1x; scale them to the render's ratio.
            out = QImage(int((560 + 2 * gap) * dpr),
                         int((len(pairs) * (2 * CROP_H + gap + 4) + gap) * dpr),
                         QImage.Format_ARGB32_Premultiplied)
            out.fill(QColor("#101114"))
            cp = QPainter(out)
            cp.setRenderHint(QPainter.SmoothPixmapTransform, True)
            y = gap
            for image, (_n, _m, width, (cx, cy)) in pairs:
                crop = design.copy(QRect(cx, cy, width, CROP_H))
                cp.drawImage(QRect(int(gap * dpr), int(y * dpr),
                                   int(width * dpr), int(CROP_H * dpr)), crop)
                cp.drawImage(QPoint(int(gap * dpr), int((y + CROP_H + 4) * dpr)), image)
                y += 2 * CROP_H + gap + 4
            cp.end()
            out.save(os.path.join(ARGS.outdir, f"{style}-compare.png"))
    print(f"wrote {len(STATES) * len(tokens.STYLES)} states to {ARGS.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
