"""Tests for ToonPortraitWidget override pickup + widened pencil visibility."""

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


def test_widget_subscribes_to_fetcher_singleton(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    # The widget must hold a reference to the singleton.
    assert w._fetcher is RenditionPoseFetcher.instance()


def test_widget_filters_stale_pose_ready_by_dna(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from PySide6.QtGui import QPixmap
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(RenditionPoseFetcher, "request", lambda *a, **k: None)
    from tabs.multitoon._tab import ToonPortraitWidget
    from utils.toon_customizations_manager import ToonCustomizationsManager

    w = ToonPortraitWidget(1)
    w.set_customizations_manager(ToonCustomizationsManager())
    w.set_game("ttr")
    w.set_toon_name("Flossbud")
    w.set_dna("dna-current")  # widget now tracks dna-current
    pm = QPixmap(10, 10); pm.fill()

    # Simulate a stale signal from a prior DNA.
    w._on_pose_ready("dna-stale", "portrait", pm)
    assert w._pixmap is None, "stale pose_ready must be dropped"

    # Matching signal applies.
    w._on_pose_ready("dna-current", "portrait", pm)
    assert w._pixmap is not None


def test_widget_current_portrait_transform(qt_app, monkeypatch, tmp_path):
    """Regression: the widget exposes its current portrait transform
    via a test hook so paint-time behavior can be inspected without a
    pixel-grab. Default = (1.0, 0.0, 0.0, 0.0)."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.rendition_poses import RenditionPoseFetcher
    RenditionPoseFetcher._instance = None
    monkeypatch.setattr(RenditionPoseFetcher, "request", lambda *a, **k: None)
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
