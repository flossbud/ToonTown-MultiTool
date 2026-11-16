"""Next-UI glyphs: each renders ink of the requested colour at strip and
sheet sizes, in a light-theme and a dark-theme colour."""

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from utils.icon_factory import (
    make_dpad_icon, make_grip_icon, make_key_icon, make_padlock_icon,
    make_person_icon, make_star_icon, make_window_icon,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


MAKERS = {
    "star": lambda sz, c: make_star_icon(sz, c),
    "star_filled": lambda sz, c: make_star_icon(sz, c, filled=True),
    "person": make_person_icon,
    "dpad": make_dpad_icon,
    "key": make_key_icon,
    "padlock": lambda sz, c: make_padlock_icon(sz, c),
    "padlock_open": lambda sz, c: make_padlock_icon(sz, c, unlocked=True),
    "grip": make_grip_icon,
    "window": make_window_icon,
}
COLOURS = {"light": "#1f2937", "dark": "#f2f2f2"}


def _image(name, size, colour):
    pm = MAKERS[name](size, QColor(colour)).pixmap(size, size)
    assert not pm.isNull()
    assert (pm.width(), pm.height()) == (size, size)
    return pm.toImage().convertToFormat(QImage.Format_ARGB32)


def _ink(img):
    """(count of pixels with any alpha, the most opaque pixel's colour)."""
    count, best, best_a = 0, None, -1
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 0:
                count += 1
                if c.alpha() > best_a:
                    best, best_a = c, c.alpha()
    return count, best


def _alpha_sum(img):
    return sum(img.pixelColor(x, y).alpha()
               for y in range(img.height()) for x in range(img.width()))


@pytest.mark.parametrize("name", list(MAKERS))
@pytest.mark.parametrize("size", [16, 28])
@pytest.mark.parametrize("theme", list(COLOURS))
def test_glyph_renders_in_requested_colour(app, name, size, theme):
    img = _image(name, size, COLOURS[theme])
    count, best = _ink(img)
    assert count > size, f"{name} at {size}px drew almost nothing"
    assert count < size * size, f"{name} at {size}px filled the whole square"
    want = QColor(COLOURS[theme])
    assert best.alpha() == 255
    assert abs(best.red() - want.red()) <= 2
    assert abs(best.green() - want.green()) <= 2
    assert abs(best.blue() - want.blue()) <= 2


@pytest.mark.parametrize("size", [16, 28])
def test_filled_star_has_more_ink_than_outline(app, size):
    outline = _alpha_sum(_image("star", size, "#ffffff"))
    filled = _alpha_sum(_image("star_filled", size, "#ffffff"))
    assert filled > outline


@pytest.mark.parametrize("size", [16, 28])
def test_open_and_closed_padlock_differ(app, size):
    closed = _image("padlock", size, "#ffffff")
    opened = _image("padlock_open", size, "#ffffff")
    assert closed != opened


def test_default_colour_is_white(app):
    img = make_grip_icon(16).pixmap(16, 16).toImage()
    _, best = _ink(img.convertToFormat(QImage.Format_ARGB32))
    assert (best.red(), best.green(), best.blue()) == (255, 255, 255)
