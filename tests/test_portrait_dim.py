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
