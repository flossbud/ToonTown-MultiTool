"""Render every float-strip state offscreen and save PNGs.

A construction check: it shows what the painter draws, not how a strip
behaves on a real desktop. Each state is the real StripWidget mounted in a
parent that paints the handoff's striped stand-in for a game viewport, 10 px
from the top, the way the spec sheet shows it.

    python scripts/strip_render.py OUTDIR [--scale 2] [--size small] [--fonts DIR]
                                   [--compare SCREENSHOT_DIR]

Besides one PNG per state it writes <style>-sizes.png: the strip at small,
medium and large over a bright sky, grass and a dark scene, which is where
the drop shadow and the pixel grid show.
<style>-editor-locked.png shows the read-only game keys in both editor
layouts at all three sizes, mounted in their real popover surface.

--scale     device pixel ratio of the renders (default 1, the screenshots' ratio)
--size      strip size of the per-state renders: small (default, the size
            the handoff's screenshots are at), medium or large
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
    ap.add_argument("--size", default="small",
                    choices=("small", "medium", "large"))
    ap.add_argument("--fonts", default=None)
    ap.add_argument("--compare", default=None)
    return ap.parse_args(argv)


ARGS = _parse(sys.argv[1:])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt                      # noqa: E402
from PySide6.QtGui import (QColor, QFontDatabase, QImage,          # noqa: E402
                           QPainter)
from PySide6.QtWidgets import QApplication, QWidget                # noqa: E402

from utils import logical_actions, settings_keys                   # noqa: E402
from utils.overlay.backend import NoOpOverlayBackend               # noqa: E402
from utils.strips import tokens                                    # noqa: E402
from utils.strips.attach import AttachStrategy                     # noqa: E402
from utils.strips.model import StripModel                          # noqa: E402
from utils.strips.strip_surface import ANCHOR_INSET                # noqa: E402
from utils.strips.strip_widget import StripWidget                  # noqa: E402
from utils.strips.popovers.editor import (EditorModel, KeysetEditor,  # noqa: E402
                                          action_label)
from utils.strips.popovers.surface import PopoverSurface            # noqa: E402

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


# Flat stand-ins for what a strip really sits on: Toontown's daytime sky and
# grass are the bright cases, a building interior the dark one.
BACKGROUNDS = (("sky", "#8fd3ff"), ("grass", "#5fbf3c"), ("dark", "#1b1d22"))


class Viewport(QWidget):
    """The handoff's stand-in for a game viewport: diagonal stripes, or one
    flat colour."""

    def __init__(self, width: int, height: int = CROP_H,
                 colour: str | None = None) -> None:
        super().__init__()
        self._colour = colour
        self.setFixedSize(width, height)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        if self._colour is not None:
            p.fillRect(self.rect(), QColor(self._colour))
            return
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


def render_state(style: str, model: StripModel, width: int,
                 size: str | None = None, colour: str | None = None) -> QImage:
    """One strip on a viewport `width` px wide, placed the way the surface
    places it. `width` is the game window's width in screen px."""
    k = settings_keys.float_strip_size_factor(size or ARGS.size)
    height = int(round(CROP_H * (k if colour is not None else max(1.0, k))))
    view = Viewport(width, height, colour)
    strip = StripWidget(view)
    strip.set_style(style)
    strip.set_scale(k)
    strip.set_client_width(width / k)
    strip.set_model(model)
    row, offset = strip.row_size(), strip.row_offset()
    # Row centred, its top edge the anchor inset inside the viewport.
    strip.move(int(round((width - row.width()) / 2 - offset.x())),
               int(round(ANCHOR_INSET * k - offset.y())))
    view.show()
    QApplication.processEvents()
    dpr = ARGS.scale
    image = QImage(int(round(width * dpr)), int(round(height * dpr)),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    view.render(image)
    image.setDevicePixelRatio(1.0)
    view.close()
    view.deleteLater()
    return image


SIZE_STATES = (FLOSSBUD.with_(home=True, keysets=(1, 2, 3), active=2,
                              click_sync=False),
               HECTOR.with_(enabled=False, hidden_sets=True))
SIZE_W = 780


def render_sizes(style: str) -> QImage:
    """Small, medium and large down the page, sky, grass and dark across;
    in each cell a running toon above a disabled one."""
    dpr, gap = ARGS.scale, 8
    cells = []
    for size in settings_keys.FLOAT_STRIP_SIZE_VALUES:
        cells.append([[render_state(style, model, SIZE_W, size, colour)
                       for model in SIZE_STATES]
                      for _name, colour in BACKGROUNDS])
    heights = [sum(img.height() for img in row[0]) for row in cells]
    sheet = QImage(int((len(BACKGROUNDS) * (SIZE_W + gap) + gap) * dpr),
                   int(sum(heights) + (len(cells) + 1) * gap * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#101114"))
    sp = QPainter(sheet)
    y = int(gap * dpr)
    for row, height in zip(cells, heights):
        for col, images in enumerate(row):
            x, cy = int((gap + col * (SIZE_W + gap)) * dpr), y
            for image in images:
                sp.drawImage(QPoint(x, cy), image)
                cy += image.height()
        y += height + int(gap * dpr)
    sp.end()
    return sheet


def render_locked_editors(style: str) -> QImage:
    """Both layouts at each preset, using the real surface/content tree."""
    binds = dict(forward='w', reverse='s', left='a', right='d', jump='space',
                 book='F8', gags='g', tasks='t', map='Shift_L', action='BackSpace')
    model = EditorModel(1, tuple((a, action_label(a, logical_actions.ACTION_LABELS[a]))
                                for a in logical_actions.actions_for('ttr')),
                        tuple(binds.items()), read_only=True)
    cells = []
    for kind in ('list', 'keys'):
        row = []
        for size in settings_keys.FLOAT_STRIP_SIZE_VALUES:
            k = settings_keys.float_strip_size_factor(size)
            card = KeysetEditor(model, kind, style, k)
            surface = PopoverSurface(AttachStrategy(), NoOpOverlayBackend(), card)
            surface.present(QPoint(0, 0), None)
            for _ in range(4):
                QApplication.processEvents()
            dpr = ARGS.scale
            image = QImage(round(surface.width() * dpr), round(surface.height() * dpr),
                           QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.transparent)
            surface.render(image)
            image.setDevicePixelRatio(1.0)
            image.save(os.path.join(ARGS.outdir, f'{style}-editor-locked-{size}-{kind}.png'))
            row.append(image)
            surface.dismiss()
        cells.append(row)
    gap = round(12 * ARGS.scale)
    sheet = QImage(sum(img.width() for img in cells[0]) + 4 * gap,
                   sum(max(img.height() for img in row) for row in cells) + 3 * gap,
                   QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#101114'))
    p = QPainter(sheet)
    y = gap
    for row in cells:
        x = gap
        for image in row:
            p.drawImage(QPoint(x, y), image)
            x += image.width() + gap
        y += max(img.height() for img in row) + gap
    p.end()
    return sheet


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
        render_sizes(style).save(os.path.join(ARGS.outdir, f"{style}-sizes.png"))
        render_locked_editors(style).save(os.path.join(ARGS.outdir, f"{style}-editor-locked.png"))

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
