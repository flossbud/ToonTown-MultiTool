import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor, QPixmap
from tabs.multitoon._tab import ToonPortraitWidget


def _solid(w, h, color):
    pm = QPixmap(w, h)
    pm.fill(color)
    return pm


def test_dim_cache_populated_on_dimmed_paint(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    assert pw._dim_cache is None
    pw.grab()                       # force a paint
    assert pw._dim_cache is not None


def test_state_change_clears_cache(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw.set_colors("#101010", "#ffffff")   # any content setter must invalidate
    assert pw._dim_cache is None


def test_pose_ready_clears_cache(qapp):
    # The async fetch callback populates _pixmap; it MUST invalidate the dim
    # cache or a dimmed portrait stays stuck on its loading spinner.
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._dna = "x"
    pw._pose = "portrait"
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw._on_pose_ready("x", "portrait", _solid(64, 64, QColor(0, 255, 0)))
    assert pw._dim_cache is None


def test_set_game_clears_cache(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw.set_game("cc")        # game selects the render branch
    assert pw._dim_cache is None


def test_set_toon_name_clears_cache(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw.set_toon_name("Test Toon")   # name keys the customizations lookup
    assert pw._dim_cache is None


def test_set_cc_auto_species_clears_cache(qapp):
    # Async species detection can land AFTER the card is dimmed; the stale
    # cache would otherwise paint the wrong CC race badge.
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw.set_cc_auto_species("DOG")
    assert pw._dim_cache is None


def test_set_customizations_manager_clears_cache(qapp):
    # The manager drives portrait brush/pattern/silhouette/pose lookups; a late
    # injection while dimmed must rebuild the dim cache (and repaint).
    class _Mgr:
        def get(self, *a, **k):
            return {}
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(True)
    pw.grab()
    assert pw._dim_cache is not None
    pw.set_customizations_manager(_Mgr())
    assert pw._dim_cache is None


def test_not_dimmed_keeps_cache_none(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 0, 0))
    pw.set_dimmed(False)
    pw.grab()
    assert pw._dim_cache is None


def test_set_dim_progress_clamps_and_stores(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw.set_dim_progress(-1.0)
    assert pw._dim_progress == 0.0
    pw.set_dim_progress(2.0)
    assert pw._dim_progress == 1.0
    pw.set_dim_progress(0.5)
    assert pw._dim_progress == 0.5


def test_mid_progress_builds_cache_and_paints(qapp):
    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pm = QPixmap(64, 64)
    pm.fill(QColor(255, 0, 0))
    pw._pixmap = pm
    pw.set_dim_progress(0.5)
    pw.grab()                         # cross-fade path must not crash
    assert pw._dim_cache is not None  # dim pixmap needed for the blend


def test_set_dimmed_wrapper_sets_progress(qapp):
    pw = ToonPortraitWidget(1)
    pw.set_dimmed(True)
    assert pw._dim_progress == 1.0
    pw.set_dimmed(False)
    assert pw._dim_progress == 0.0


def test_float_crossfade_dims_linearly_at_reduced_opacity(qapp):
    # Regression (float/transparent-mode dim lag): in float mode the portrait is
    # composited at a REDUCED hover-peek opacity. The lit->dim cross-fade must
    # still progress ~linearly with dim_progress at that reduced opacity, so the
    # portrait dims in unison with the card body. The OLD cross-fade drew the lit
    # toon at FULL base opacity and only faded the dim copy in at base*prog, so
    # under reduced opacity the dim never covered the lit until prog==1 -> the
    # portrait stayed mostly-lit, then snapped, lagging the body's linear color
    # lerp. The fix fades lit OUT by (1-prog) as dim fades IN by prog. See
    # ToonPortraitWidget.paintEvent.
    from PySide6.QtGui import QColor, QImage, QRegion
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget

    pw = ToonPortraitWidget(1)
    pw.resize(64, 64)
    pw._pixmap = _solid(64, 64, QColor(255, 80, 20))   # vivid lit pose
    pw.set_peek_opacity(0.4)                            # transparent-mode peek

    def center_rgb(prog):
        pw.set_dim_progress(prog)
        img = QImage(64, 64, QImage.Format_ARGB32)
        img.fill(0)                                     # transparent backing
        # DrawChildren only (skip the window background) so the measured pixel is
        # the painted cross-fade over transparent, never a palette fill.
        pw.render(img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        return img.pixelColor(32, 32)

    lit = center_rgb(0.0)
    dim = center_rgb(1.0)

    def dist(a, b):
        return abs(a.red()-b.red()) + abs(a.green()-b.green()) + abs(a.blue()-b.blue())

    total = dist(lit, dim) or 1

    def frac(prog):
        return dist(lit, center_rgb(prog)) / total

    f25, f50, f75 = frac(0.25), frac(0.5), frac(0.75)
    assert f25 < f50 < f75, (f25, f50, f75)            # monotonic, not back-loaded
    # The old back-loaded curve sat near ~0.39 @0.5 and ~0.52 @0.75 at this peek;
    # the true cross-fade clears those comfortably.
    assert f50 >= 0.45, f50
    assert f75 >= 0.65, f75
