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


def _naive_dim_pixmap(pm):
    """The original per-pixel reference (pre-optimization). Used to pin the fast
    implementation to identical output and to measure the speedup."""
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            img.setPixelColor(x, y, dim_color(c))
    return QPixmap.fromImage(img)


def test_dim_pixmap_matches_naive_reference_oddwidth(qapp):
    # Multi-row + odd width (7) exercises the per-row bytesPerLine indexing (for
    # RGBA8888 w*4 is already 32-bit aligned, so this checks row arithmetic, not
    # padding per se); mixed full/partial/zero alpha exercises the alpha-preserve
    # + transparent-skip paths. The fast path must be pixel-identical (locks the
    # dim look).
    w, h = 7, 5
    img = QImage(w, h, QImage.Format_ARGB32)
    for y in range(h):
        for x in range(w):
            a = 0 if (x == 3 and y == 2) else (128 if (x + y) % 4 == 0 else 255)
            img.setPixelColor(x, y, QColor((x * 37) % 256, (y * 53) % 256,
                                           (x * y * 17) % 256, a))
    pm = QPixmap.fromImage(img)
    got = dim_pixmap(pm).toImage().convertToFormat(QImage.Format_ARGB32)
    exp = _naive_dim_pixmap(pm).toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(h):
        for x in range(w):
            cg = got.pixelColor(x, y)
            ce = exp.pixelColor(x, y)
            assert (cg.red(), cg.green(), cg.blue(), cg.alpha()) == \
                   (ce.red(), ce.green(), ce.blue(), ce.alpha()), \
                f"pixel {x},{y}: got {cg.getRgb()} expected {ce.getRgb()}"


def test_dim_pixmap_faster_than_naive(qapp):
    # Regression guard for the float-mode dim-fade snap: the per-pixel QColor loop
    # took ~52ms at 160px, blocking the GUI thread on the first fade frame and
    # stalling the animation timer. The fast path must be substantially quicker.
    # Ratio (not absolute ms) so it does not depend on host speed.
    import time
    pm = QPixmap(160, 160)
    pm.fill(QColor(120, 60, 200))
    dim_pixmap(pm)
    _naive_dim_pixmap(pm)            # warm both

    def best(fn, n=3):
        b = float("inf")
        for _ in range(n):
            t0 = time.perf_counter()
            fn(pm)
            b = min(b, time.perf_counter() - t0)
        return b

    t_fast = best(dim_pixmap)
    t_naive = best(_naive_dim_pixmap)
    assert t_fast * 3 <= t_naive, (
        f"dim_pixmap must be >=3x faster than the naive per-pixel loop: "
        f"fast={t_fast * 1e3:.1f}ms naive={t_naive * 1e3:.1f}ms"
    )


def test_lerp_color_endpoints_and_mid():
    from utils.card_dim import lerp_color
    a = QColor(0, 0, 0, 0)
    b = QColor(100, 200, 40, 255)
    assert lerp_color(a, b, 0.0) == a
    assert lerp_color(a, b, 1.0) == b
    mid = lerp_color(a, b, 0.5)
    assert (mid.red(), mid.green(), mid.blue(), mid.alpha()) == (50, 100, 20, 128)


def test_lerp_color_clamps_t():
    from utils.card_dim import lerp_color
    a = QColor(10, 10, 10, 255)
    b = QColor(20, 20, 20, 255)
    assert lerp_color(a, b, -1.0) == a
    assert lerp_color(a, b, 2.0) == b


def test_fade_constant():
    from utils.card_dim import DIM_FADE_MS
    assert DIM_FADE_MS == 200
