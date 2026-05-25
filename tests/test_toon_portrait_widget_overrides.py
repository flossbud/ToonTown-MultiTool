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
