"""Tests for ToonPortraitWidget's reads from the per-toon render cache.

The widget no longer fetches Rendition pixmaps at all - it asks the shared
ToonRenders facade for its (game, toon, pose) synchronously and repaints on
the cache's `render_landed` / `set_promoted` signals."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


PORTRAIT = "#ff0000"
GRIN = "#00ff00"
WAVING = "#0000ff"


def _land(store, game, name, dna):
    """Land every pose for `dna` - portrait / portrait-grin / waving each in
    its own colour so the pose the widget drew is visible - and promote it."""
    from tests._render_fixtures import real_png
    colours = {"portrait": PORTRAIT, "portrait-grin": GRIN, "waving": WAVING}
    store.note_dna(game, name, dna)
    for pose in store.poses:
        real_png(store.path_for(game, name, dna, pose), colours.get(pose, "#123456"))
        assert store.mark_landed(game, name, dna, pose)
    assert store.promote_if_complete(game, name)


def _drawn(w) -> str:
    assert w._pixmap is not None, "nothing drawn"
    return w._pixmap.toImage().pixelColor(0, 0).name()


def test_set_dna_reads_portrait_pose_when_no_override(render_cache, monkeypatch, tmp_path):
    """Default behavior: set_dna reads the toon's 'portrait' pose from the cache."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    facade, store, pf = render_cache
    _land(store, "ttr", "Flossbud", "dna-foo")
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_customizations_manager(ToonCustomizationsManager())
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    assert w._pixmap is None
    w.set_dna("dna-foo")
    assert w._pose == "portrait"
    assert _drawn(w) == PORTRAIT and w._loading is False


def test_set_dna_uses_pose_override_from_manager(render_cache, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    facade, store, pf = render_cache
    _land(store, "ttr", "Flossbud", "dna-foo")
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "portrait-grin"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    w.set_dna("dna-foo")

    assert w._pose == "portrait-grin"
    assert _drawn(w) == GRIN


def test_set_pose_rereads_the_cache(render_cache, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    facade, store, pf = render_cache
    _land(store, "ttr", "Flossbud", "dna-foo")
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(ToonCustomizationsManager())
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    w.set_dna("dna-foo")
    assert _drawn(w) == PORTRAIT
    w.set_pose("waving")
    assert _drawn(w) == WAVING and w._loading is False


def test_set_dna_none_clears_pixmap(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import ToonPortraitWidget
    from PySide6.QtGui import QPixmap
    w = ToonPortraitWidget(1)
    pm = QPixmap(10, 10); pm.fill()
    w._pixmap = pm
    w._tier = "current"
    w.set_dna(None)
    assert w._pixmap is None
    assert w.portrait_tier() is None


def test_set_toon_name_after_set_dna_picks_up_saved_pose(render_cache, monkeypatch, tmp_path):
    """Regression: on app restart, the data ingestion path calls
    `set_dna()` before `set_toon_name()`. The first call resolves the
    pose against an empty toon name (default "portrait") and has no cache
    key to read. When the name finally arrives, the widget must re-check
    the manager and read the saved pose from the cache."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    facade, store, pf = render_cache
    _land(store, "ttr", "Flossbud", "dna-foo")
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "portrait-grin"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    # Simulate the real-world order: set_dna FIRST (with no name yet),
    # then set_toon_name catches up.
    w.set_dna("dna-foo")
    assert w._pose == "portrait"
    assert w._pixmap is None and w._loading is False   # no key -> nothing to read

    w.set_toon_name("Flossbud")
    # Now that the name is set, the widget must read the saved pose.
    assert w._pose == "portrait-grin"
    assert _drawn(w) == GRIN


def test_set_game_after_set_dna_picks_up_saved_pose(render_cache, monkeypatch, tmp_path):
    """Sister test: if set_game runs after set_dna + set_toon_name,
    the widget re-resolves the pose under the new game namespace."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    facade, store, pf = render_cache
    _land(store, "ttr", "Flossbud", "dna-foo")
    from utils.toon_customizations_manager import ToonCustomizationsManager
    from tabs.multitoon._tab import ToonPortraitWidget
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"pose": "waving"})

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_toon_name("Flossbud")
    w.set_dna("dna-foo")  # game not yet set -> default portrait, nothing to read
    assert w._pose == "portrait"
    assert w._pixmap is None and w._loading is False

    w.set_game("ttr")
    assert w._pose == "waving"
    assert _drawn(w) == WAVING


@pytest.mark.parametrize("last", ["set_toon_name", "set_game"])
def test_key_landing_after_set_dna_reads_the_cache_and_discovers(render_cache, last):
    """The tab calls set_dna() BEFORE set_toon_name() (`_apply_merged_toon_data`)
    and set_game() arrives on its own schedule. The cache is keyed by
    (game, name), so the read AND the discovery must happen when the last
    part of the key lands - even when the pose does not change."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")

    def build(name, dna):
        w = ToonPortraitWidget(1)
        if last == "set_toon_name":
            w.set_game("ttr")
        else:
            w.set_toon_name(name)
        w.set_dna(dna)
        assert w._pixmap is None and w._loading is False   # key incomplete: nothing to read
        if last == "set_toon_name":
            w.set_toon_name(name)
        else:
            w.set_game("ttr")
        return w

    w = build("Hiro", "dna1")
    assert w._pixmap is not None and w.portrait_tier() == "current"

    assert store.candidate_dna("ttr", "Blue") is None
    v = build("Blue", "dnaX")
    assert store.candidate_dna("ttr", "Blue") == "dnaX"    # discovered once keyed
    assert v._pixmap is None and v._loading is True


def test_toon_portrait_widget_draws_circle_outline_when_set(qt_app, monkeypatch, tmp_path):
    """The TTR portrait widget paints the circle outline when set.

    Note: the widget hard-caps at 64x64 via setMaximumSize. Don't override.
    With width=64, cx=cy=32, r=30, and outline thick (width=4, inset=2),
    the outline ring is at radius 28..30 from center, so the leftmost
    outline pixel is at x = cx - 30 = 2 (rect outer edge) through x = 4."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(
        RenditionPoseFetcher, "request", lambda *a, **k: None
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager

    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {
        "portrait": {
            "color": "#000000",
            "outline": {"color": "#ffd84a", "width": "thick"},
        },
    })
    w = ToonPortraitWidget(1)
    # Use the widget's actual size (64x64 - hard-capped).
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    pm = w.grab()
    img = pm.toImage()
    # Walk inward at vertical center looking for the FIRST YELLOW pixel.
    # The widget background may paint solid pixels in the corners, so we
    # filter for the outline color specifically rather than any opaque pixel.
    cy = 32  # 64 / 2
    found_yellow = False
    for x in range(0, 10):
        px = img.pixelColor(x, cy)
        if px.red() > 200 and px.green() > 180 and px.blue() < 120:
            found_yellow = True
            break
    assert found_yellow, (
        f"never saw a yellow outline pixel walking inward from x=0..9 at y={cy}. "
        f"sampled colors: {[img.pixelColor(x, cy).name() for x in range(0, 10)]}"
    )


def test_toon_portrait_invokes_silhouette_builders_when_set(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    import utils.portrait_effects as eff
    calls = []
    monkeypatch.setattr(
        eff, "build_silhouette_outline_pixmap",
        lambda pm, c, w: (calls.append(("out", c.name(), w)), QPixmap(pm.size()))[1],
    )
    monkeypatch.setattr(
        eff, "build_silhouette_shadow_pixmap",
        lambda pm, c, b: (calls.append(("shd", c.name(), b)),
                          QPixmap(pm.width() + 2 * b, pm.height() + 2 * b))[1],
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"portrait": {"silhouette": {
        "outline": {"color": "#ffd84a", "width": "medium"},
        "shadow":  {"color": "#000000", "softness": "medium"},
    }}})
    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    # Inject a fake pose pixmap so paint has something to draw.
    fake = QPixmap(64, 64); fake.fill(Qt.red)
    w._pixmap = fake
    w.show()
    w.repaint()
    qt_app.processEvents()
    assert ("out", "#ffd84a", 2) in calls
    assert ("shd", "#000000", 12) in calls


def test_toon_portrait_silhouette_cache_hits_on_unchanged_repaint(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    import utils.portrait_effects as eff
    calls = []
    monkeypatch.setattr(
        eff, "build_silhouette_outline_pixmap",
        lambda pm, c, w: (calls.append("out"), QPixmap(pm.size()))[1],
    )
    monkeypatch.setattr(
        eff, "build_silhouette_shadow_pixmap",
        lambda pm, c, b: (calls.append("shd"),
                          QPixmap(pm.width() + 2 * b, pm.height() + 2 * b))[1],
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    mgr.set("ttr", "Flossbud", {"portrait": {"silhouette": {
        "outline": {"color": "#ffd84a", "width": "medium"},
    }}})
    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    fake = QPixmap(64, 64); fake.fill(Qt.red)
    w._pixmap = fake
    w.show()
    w.repaint(); qt_app.processEvents()
    n = len(calls)
    assert n == 1
    w.repaint(); qt_app.processEvents()
    assert len(calls) == n  # cached


def test_cc_portrait_draws_circle_outline_when_set(qt_app, monkeypatch, tmp_path):
    """CC mode renders via paint_cc_badge. The badge function must accept
    the new circle_outline kwarg and draw the ring on top."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtGui import QColor
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager

    mgr = ToonCustomizationsManager()
    mgr.set("cc", "CCToon", {
        "portrait": {"outline": {"color": "#ffd84a", "width": "thick"}}
    })
    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("cc")
    w.set_toon_name("CCToon")
    # CC mode requires _cc_mode + _cc_skin to engage the CC paint path.
    w._cc_mode = True
    w._cc_skin = QColor("#d9a04e")
    pm = w.grab()
    img = pm.toImage()
    # Widget is 64x64 (hard-capped). Walk inward at vertical center
    # looking for the FIRST YELLOW pixel.
    cy = 32
    found_yellow = False
    for x in range(0, 10):
        px = img.pixelColor(x, cy)
        if px.red() > 200 and px.green() > 180 and px.blue() < 120:
            found_yellow = True
            break
    assert found_yellow, (
        f"never saw a yellow outline pixel walking inward at y={cy}. "
        f"sampled: {[img.pixelColor(x, cy).name() for x in range(0, 10)]}"
    )


def test_cc_portrait_invokes_silhouette_builders_when_set(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    import utils.portrait_effects as eff
    calls = []
    monkeypatch.setattr(
        eff, "build_silhouette_outline_pixmap",
        lambda pm, c, w: (calls.append(("out", c.name(), w)), QPixmap(pm.size()))[1],
    )
    monkeypatch.setattr(
        eff, "build_silhouette_shadow_pixmap",
        lambda pm, c, b: (calls.append(("shd", c.name(), b)),
                          QPixmap(pm.width() + 2 * b, pm.height() + 2 * b))[1],
    )
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    mgr.set("cc", "CCToon", {"portrait": {"silhouette": {
        "outline": {"color": "#ffd84a", "width": "thin"},
        "shadow":  {"color": "#000000", "softness": "subtle"},
    }}})
    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("cc")
    w.set_toon_name("CCToon")
    w._cc_mode = True
    w._cc_skin = QColor("#d9a04e")
    fake = QPixmap(64, 64); fake.fill(Qt.red)
    w._pixmap = fake
    w.show()
    w.repaint(); qt_app.processEvents()
    assert ("out", "#ffd84a", 1) in calls
    assert ("shd", "#000000", 6) in calls
