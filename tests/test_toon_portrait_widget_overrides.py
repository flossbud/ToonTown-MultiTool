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
    assert w._pixmap is None and w._loading is True
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
    assert w._pixmap is None and w._loading is True
    pf.set_promoted.emit("ttr", "Hiro")
    assert w._pixmap is not None


def test_portrait_widget_reads_the_toon_cache_and_discovers(render_cache, qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000")
    w = ToonPortraitWidget(slot=0)
    w.set_game("ttr")
    w.set_toon_name("Hiro")
    w.set_dna("dna1")
    assert w._pixmap is not None and w._loading is False
    assert w.portrait_tier() == "current"
    w.set_dna("dna2")                                   # new outfit
    assert store.candidate_dna("ttr", "Hiro") == "dna2" # discovered
    assert w.portrait_tier() == "previous"              # still drawn from dna1
    assert w._loading is False


def test_portrait_widget_repaints_only_for_its_own_pose(render_cache, qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    from tests._render_fixtures import complete_set
    facade, store, pf = render_cache
    store.note_dna("ttr", "Hiro", "dna1")
    w = ToonPortraitWidget(slot=0)
    w.set_game("ttr"); w.set_toon_name("Hiro"); w.set_dna("dna1")
    assert w._pixmap is None and w._loading is True
    complete_set(store, "ttr", "Hiro", "dna1")
    pf.render_landed.emit("ttr", "Hiro", "waving")
    assert w._pixmap is None
    pf.render_landed.emit("ttr", "Hiro", w._pose)
    assert w._pixmap is not None and w._loading is False


def test_portrait_widget_survives_a_cache_failure(render_cache, monkeypatch):
    """A cache failure must never break the Multitoon tab: a raising read or
    discovery is contained, the badge falls back to its slot circle (no
    spinner left running) and a later good read still lands."""
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
