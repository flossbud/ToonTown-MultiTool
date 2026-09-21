"""Tests for ToonPortraitWidget override pickup, widened pencil visibility,
and its reads from the per-toon render cache (ToonRenders)."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _send_left_click(widget, local_pos: QPoint) -> None:
    press = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(local_pos),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.MouseButtonRelease, QPointF(local_pos),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    widget.mousePressEvent(press)
    widget.mouseReleaseEvent(release)


def _new_widget(qt_app, monkeypatch, tmp_path, *, game, toon_name):
    """Build a widget wired to a fresh ToonCustomizationsManager."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_customizations_manager(mgr)
    w.set_game(game)
    w.set_toon_name(toon_name)
    return w, mgr


def test_pencil_appears_when_name_and_game_known(qt_app, monkeypatch, tmp_path):
    """TTR badge (no CC mode) shows pencil when name + game both set."""
    w, _ = _new_widget(qt_app, monkeypatch, tmp_path, game="ttr", toon_name="Flossbud")
    from utils.cc_badge_paint import pencil_rect_for
    edits: list[bool] = []
    w.edit_icon_requested.connect(lambda: edits.append(True))
    _send_left_click(w, pencil_rect_for(w.rect()).center())
    assert edits == [True]


def test_pencil_suppressed_when_game_unknown(qt_app, monkeypatch, tmp_path):
    """Pencil suppressed when game tag is None even if name is set."""
    w, _ = _new_widget(qt_app, monkeypatch, tmp_path, game=None, toon_name="Flossbud")
    from utils.cc_badge_paint import pencil_rect_for
    edits: list[bool] = []
    clicks: list[bool] = []
    w.edit_icon_requested.connect(lambda: edits.append(True))
    w.clicked.connect(lambda: clicks.append(True))
    _send_left_click(w, pencil_rect_for(w.rect()).center())
    assert edits == []
    assert clicks == [True]


def test_pencil_suppressed_when_name_missing(qt_app, monkeypatch, tmp_path):
    w, _ = _new_widget(qt_app, monkeypatch, tmp_path, game="ttr", toon_name=None)
    from utils.cc_badge_paint import pencil_rect_for
    edits: list[bool] = []
    clicks: list[bool] = []
    w.edit_icon_requested.connect(lambda: edits.append(True))
    w.clicked.connect(lambda: clicks.append(True))
    _send_left_click(w, pencil_rect_for(w.rect()).center())
    assert edits == []
    assert clicks == [True]


def test_game_property_round_trip(qt_app, monkeypatch, tmp_path):
    w, _ = _new_widget(qt_app, monkeypatch, tmp_path, game="cc", toon_name="Flossbud")
    assert w.game == "cc"
    w.set_game("ttr")
    assert w.game == "ttr"


def test_paint_does_not_crash_without_manager(qt_app):
    """Widget constructed with neither manager nor game still paints."""
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    w.resize(64, 64)
    w.show()
    qt_app.processEvents()
    w.hide()


def test_paint_picks_up_portrait_color_override(qt_app, monkeypatch, tmp_path):
    """When manager has a portrait color, paintEvent uses the resolver
    to pick the brush. Verified via the public `current_portrait_brush()`
    test hook on the widget (added in step 3)."""
    w, mgr = _new_widget(qt_app, monkeypatch, tmp_path, game="ttr", toon_name="Flossbud")
    mgr.set("ttr", "Flossbud", {"portrait": {"color": "#abcdef"}})
    from PySide6.QtGui import QColor
    brush = w.current_portrait_brush()
    assert brush.color() == QColor("#abcdef")


def test_pencil_overlay_paints_for_ttr_on_hover(qt_app, monkeypatch, tmp_path):
    """Regression: when hovered, the pencil overlay must be drawn on the
    TTR badge (not just on CC). Verified by grabbing the widget pixmap
    and checking that the pencil region differs from the surrounding
    circle - i.e. something was painted over the bg in that area."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QEnterEvent
    from utils.cc_badge_paint import pencil_rect_for

    w, _ = _new_widget(qt_app, monkeypatch, tmp_path, game="ttr", toon_name="Flossbud")
    # Force hover state on
    enter = QEnterEvent(QPointF(50, 50), QPointF(50, 50), QPointF(50, 50))
    w.enterEvent(enter)
    w.show()
    qt_app.processEvents()

    pm = w.grab()
    img = pm.toImage()
    rect = pencil_rect_for(w.rect())
    # Pencil overlay paints a near-white circle bg. Center pixel of the
    # pencil rect should be near-white (R>200, G>200, B>200) when the
    # overlay is rendered, vs the bg colour when it is not.
    center = img.pixelColor(rect.center().x(), rect.center().y())
    assert center.red() > 200 and center.green() > 200 and center.blue() > 200, (
        f"Expected near-white pencil overlay bg at {rect.center()}, got "
        f"{center.getRgb()}"
    )
    w.hide()


def test_widget_subscribes_to_the_toon_cache(render_cache):
    """The widget reads the process-wide ToonRenders and its `set_promoted`
    wiring is live: a promotion for its toon lands the portrait."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    w = ToonPortraitWidget(1)
    assert w._renders is facade
    w.set_game("ttr"); w.set_toon_name("Hiro"); w.set_dna("dna1")
    assert w._pixmap is None and w._loading is False   # nothing on disk: slot circle
    complete_set(store, "ttr", "Hiro", "dna1")
    pf.set_promoted.emit("ttr", "Hiro")
    assert w._pixmap is not None and w._loading is False
    assert w.portrait_tier() == "current"


def test_widget_ignores_landings_for_other_toons(render_cache):
    """The facade is process-wide: a landing or a promotion for ANOTHER
    toon (or the same name under another game) must not repaint this
    widget. The legacy stale-DNA filter, re-keyed on (game, name)."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    w = ToonPortraitWidget(1)
    w.set_game("ttr"); w.set_toon_name("Hiro"); w.set_dna("dna1")
    complete_set(store, "ttr", "Hiro", "dna1")
    pf.render_landed.emit("ttr", "Other", w._pose)
    pf.set_promoted.emit("ttr", "Other")
    pf.render_landed.emit("cc", "Hiro", w._pose)
    pf.set_promoted.emit("cc", "Hiro")
    assert w._pixmap is None and w._loading is False
    pf.set_promoted.emit("ttr", "Hiro")
    assert w._pixmap is not None


def test_the_badge_never_discovers_only_the_hook_does(render_cache, monkeypatch):
    """Discovery has exactly one source: the capture hook in
    `_capture_account_toon`, which owns the atomic (wid, name, dna) triple
    (plus the startup sweep). A badge is a reader. Whatever order its
    setters run in - the tab calls set_dna before set_toon_name, and a
    window shift calls set_dna alone - it must never write to the store:
    a `discovered()` under a stale name would hand one toon's outfit to
    another and, once landed, paint the wrong body on that toon's card."""
    import itertools
    from tabs.multitoon._tab import ToonPortraitWidget
    facade, store, pf = render_cache
    seen: list[tuple] = []
    monkeypatch.setattr(facade, "discovered", lambda *a, **k: seen.append(a))
    steps = {
        "set_game":      lambda w: w.set_game("ttr"),
        "set_toon_name": lambda w: w.set_toon_name("Hiro"),
        "set_dna":       lambda w: w.set_dna("dna1"),
        "set_toon":      lambda w: w.set_toon("Blue", "dna2"),
        "set_pose":      lambda w: w.set_pose("waving"),
    }
    for order in itertools.permutations(steps):
        w = ToonPortraitWidget(1)
        for step in order:
            steps[step](w)
        # ...and once more on a complete key, changing each part in turn.
        w.set_dna("dna3"); w.set_toon_name("Hiro"); w.set_game("cc")
        w.set_toon("Blue", "dna1"); w.set_pose("portrait")
    assert seen == []
    for game, name in itertools.product(("ttr", "cc"), ("Hiro", "Blue")):
        assert store.candidate_dna(game, name) is None
        assert store.current_dna(game, name) is None


def test_set_toon_reads_the_new_toon_not_a_half_updated_key(render_cache, monkeypatch):
    """`set_toon(name, dna)` assigns both halves of the key and reads ONCE:
    never the old name under the new DNA, never the new name before its
    DNA is in place."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    complete_set(store, "ttr", "Blue", "dna2", "#00ff00")
    w = ToonPortraitWidget(1)
    w.set_game("ttr"); w.set_toon("Hiro", "dna1")
    assert w._pixmap.toImage().pixelColor(0, 0).name() == "#ff0000"
    reads: list[tuple] = []
    real = facade.pixmap_for
    monkeypatch.setattr(facade, "pixmap_for",
                        lambda g, n, pose: (reads.append((g, n, pose)), real(g, n, pose))[1])
    w.set_toon("Blue", "dna2")
    assert reads == [("ttr", "Blue", w._pose)]
    assert w._pixmap.toImage().pixelColor(0, 0).name() == "#00ff00"
    assert w.toon_name == "Blue" and w._dna == "dna2"


def test_set_toon_is_a_noop_for_an_unchanged_key(render_cache, monkeypatch):
    """The tab calls set_toon on every poll tick; an unchanged (name, dna)
    must not re-read the cache (nor invalidate the dim cache)."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    w = ToonPortraitWidget(1)
    w.set_game("ttr"); w.set_toon("Hiro", "dna1")
    reads: list[tuple] = []
    monkeypatch.setattr(facade, "pixmap_for", lambda *a: reads.append(a))
    w.set_toon("Hiro", "dna1")
    assert reads == [] and w._pixmap is not None


def test_nothing_on_disk_paints_the_slot_circle_not_the_ellipsis(render_cache):
    """A miss is not "loading": nothing in the cache world ever clears a
    `_loading = True` (a permanently failing download would leave the
    ellipsis up forever), so the badge paints its slot circle - exactly
    what a badge that was never given a toon paints - and the cache's
    `render_landed` / `set_promoted` repaint it when art arrives."""
    from tabs.multitoon._tab import ToonPortraitWidget
    facade, store, pf = render_cache
    w = ToonPortraitWidget(1); w.resize(64, 64)
    w.set_game("ttr"); w.set_toon("Hiro", "dna1")          # nothing on disk
    assert w._pixmap is None and w._loading is False
    miss = w.grab().toImage()
    ref = ToonPortraitWidget(1); ref.resize(64, 64)      # never given a toon
    assert miss == ref.grab().toImage()                  # the slot circle
    ref._loading = True                                  # the ellipsis branch
    assert miss != ref.grab().toImage()


def test_previous_look_sets_the_tooltip_and_current_clears_it(render_cache):
    """Tier "previous" (the last complete look shown while a newer outfit
    downloads) carries the facade's PREVIOUS_LOOK_TOOLTIP; any other state
    clears it."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    from utils.toon_renders import PREVIOUS_LOOK_TOOLTIP
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1")
    w = ToonPortraitWidget(1)
    w.set_game("ttr"); w.set_toon("Hiro", "dna1")
    assert w.portrait_tier() == "current" and w.toolTip() == ""
    store.note_dna("ttr", "Hiro", "dna2")        # the hook discovered a new outfit
    w.set_toon("Hiro", "dna2")                   # the tab's next tick: candidate pending
    assert w.portrait_tier() == "previous"
    assert w.toolTip() == PREVIOUS_LOOK_TOOLTIP
    complete_set(store, "ttr", "Hiro", "dna2")
    pf.set_promoted.emit("ttr", "Hiro")
    assert w.portrait_tier() == "current" and w.toolTip() == ""
    w.set_dna(None)
    assert w.toolTip() == ""


def test_portrait_widget_repaints_only_for_its_own_pose(render_cache, qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    store.note_dna("ttr", "Hiro", "dna1")
    w = ToonPortraitWidget(slot=0)
    w.set_game("ttr"); w.set_toon_name("Hiro"); w.set_dna("dna1")
    assert w._pixmap is None and w._loading is False
    complete_set(store, "ttr", "Hiro", "dna1")
    pf.render_landed.emit("ttr", "Hiro", "waving")
    assert w._pixmap is None
    pf.render_landed.emit("ttr", "Hiro", w._pose)
    assert w._pixmap is not None and w._loading is False


def test_portrait_widget_survives_a_cache_failure(render_cache, monkeypatch):
    """A cache failure must never break the Multitoon tab: a raising read is
    contained, the badge falls back to its slot circle (no spinner left
    running) and a later good read still lands. `discovered` raising too
    doubles as a guard that the badge never calls it."""
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache

    def _boom(*a, **k):
        raise RuntimeError("cache exploded")

    monkeypatch.setattr(facade, "pixmap_for", _boom)
    monkeypatch.setattr(facade, "discovered", _boom)
    w = ToonPortraitWidget(1)
    w.set_game("ttr"); w.set_toon_name("Hiro")
    w.set_dna("dna1")                        # must not raise
    assert w._pixmap is None and w._loading is False and w.portrait_tier() is None
    pf.render_landed.emit("ttr", "Hiro", w._pose)   # handler must not raise either
    monkeypatch.undo()
    complete_set(store, "ttr", "Hiro", "dna1")
    pf.set_promoted.emit("ttr", "Hiro")
    assert w._pixmap is not None and w.portrait_tier() == "current"


def test_widget_current_portrait_transform(qt_app, monkeypatch, tmp_path):
    """Regression: the widget exposes its current portrait transform
    via a test hook so paint-time behavior can be inspected without a
    pixel-grab. Default = (1.0, 0.0, 0.0, 0.0)."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(mgr)
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    assert w.current_portrait_transform() == (1.0, 0.0, 0.0, 0.0)

    mgr.set("ttr", "Flossbud", {
        "portrait": {
            "transform": {
                "zoom": 1.5,
                "offset_x": 0.2,
                "offset_y": -0.1,
                "rotate": 45.0,
            }
        }
    })
    assert w.current_portrait_transform() == (1.5, 0.2, -0.1, 45.0)
