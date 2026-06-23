import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor, QImage, QPixmap
from utils.card_dim import dim_color, dim_pixmap, SAT, BRIGHT


def test_constants():
    assert SAT == 0.45 and BRIGHT == 0.75


def test_dim_color_pure_red():
    # lum = 0.3*255 = 76.5
    # ch_r = (255*0.45 + 76.5*0.55) * 0.75 = 156.825*0.75 = 117.619 -> 118
    # ch_g = ch_b = (0 + 76.5*0.55) * 0.75 = 42.075*0.75 = 31.55 -> 32
    out = dim_color(QColor(255, 0, 0, 255))
    assert (out.red(), out.green(), out.blue()) == (118, 32, 32)


def test_dim_color_preserves_alpha():
    out = dim_color(QColor(10, 200, 90, 137))
    assert out.alpha() == 137


def test_dim_color_grey_is_only_darkened():
    # A fully desaturated input keeps its hue-lessness; only brightness 0.75 applies.
    out = dim_color(QColor(100, 100, 100, 255))
    assert (out.red(), out.green(), out.blue()) == (75, 75, 75)


def test_dim_pixmap_skips_transparent_and_dims_opaque(qapp):
    img = QImage(3, 1, QImage.Format_ARGB32)
    img.setPixelColor(0, 0, QColor(0, 0, 0, 0))       # transparent -> untouched
    img.setPixelColor(1, 0, QColor(255, 0, 0, 255))   # opaque red -> dimmed
    img.setPixelColor(2, 0, QColor(255, 0, 0, 128))   # semi-transparent red
    out = dim_pixmap(QPixmap.fromImage(img)).toImage()
    assert out.pixelColor(0, 0).alpha() == 0
    r = out.pixelColor(1, 0)
    assert (r.red(), r.green(), r.blue()) == (118, 32, 32)
    # Semi-transparent: RGB dimmed, alpha preserved.
    s = out.pixelColor(2, 0)
    assert (s.red(), s.green(), s.blue()) == (118, 32, 32)
    assert s.alpha() == 128


def test_dim_pixmap_null_passthrough(qapp):
    pm = QPixmap()
    assert dim_pixmap(pm).isNull()
