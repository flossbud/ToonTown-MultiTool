"""Tests for the pencil overlay and edit_icon_requested signal."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from tabs.multitoon._tab import ToonPortraitWidget  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _send_left_click(widget, local_pos: QPoint) -> None:
    """Synthesize a left-button press at local_pos and dispatch it."""
    press = QMouseEvent(
        QMouseEvent.MouseButtonPress,
        QPointF(local_pos),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    widget.mousePressEvent(press)


@pytest.fixture
def cc_widget(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.cc_race_overrides_manager import CCRaceOverridesManager
    mgr = CCRaceOverridesManager()
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_overrides_manager(mgr)
    w.set_toon_name("Flossbud")
    w.set_cc_auto_species("DOG")
    w.set_cc_mode(
        skin_rgb=(0.84, 0.19, 0.19),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )
    return w


def test_signal_exists(cc_widget):
    assert hasattr(cc_widget, "edit_icon_requested")


def test_click_in_pencil_rect_emits_edit_signal(cc_widget):
    from utils.cc_badge_paint import pencil_rect_for
    rect = pencil_rect_for(cc_widget.rect())
    received = []
    cc_widget.edit_icon_requested.connect(lambda: received.append(True))
    _send_left_click(cc_widget, rect.center())
    assert received == [True], "edit_icon_requested should fire"


def test_click_in_pencil_rect_does_not_emit_clicked(cc_widget):
    from utils.cc_badge_paint import pencil_rect_for
    rect = pencil_rect_for(cc_widget.rect())
    received = []
    cc_widget.clicked.connect(lambda: received.append(True))
    _send_left_click(cc_widget, rect.center())
    assert received == [], "clicked should NOT fire when pencil was hit"


def test_click_outside_pencil_emits_clicked(cc_widget):
    received = []
    cc_widget.clicked.connect(lambda: received.append(True))
    # Top-right area, far from bottom-left pencil rect.
    _send_left_click(cc_widget, QPoint(80, 16))
    assert received == [True]


def test_pencil_only_appears_in_cc_mode(qt_app, monkeypatch, tmp_path):
    """In non-CC mode, click anywhere should fire clicked, not edit."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.cc_race_overrides_manager import CCRaceOverridesManager
    mgr = CCRaceOverridesManager()
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_overrides_manager(mgr)
    # NOTE: no set_cc_mode call -> stays in non-CC mode.

    from utils.cc_badge_paint import pencil_rect_for
    rect = pencil_rect_for(w.rect())

    edits = []
    clicks = []
    w.edit_icon_requested.connect(lambda: edits.append(True))
    w.clicked.connect(lambda: clicks.append(True))
    _send_left_click(w, rect.center())
    assert edits == []
    assert clicks == [True]


def test_pencil_requires_toon_name(qt_app, monkeypatch, tmp_path):
    """CC mode but no toon_name -> pencil suppressed, click fires clicked."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.cc_race_overrides_manager import CCRaceOverridesManager
    mgr = CCRaceOverridesManager()
    w = ToonPortraitWidget(1)
    w.resize(96, 96)
    w.set_overrides_manager(mgr)
    w.set_cc_mode(
        skin_rgb=(0.5, 0.5, 0.5),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )
    # No toon_name set.

    from utils.cc_badge_paint import pencil_rect_for
    rect = pencil_rect_for(w.rect())

    edits = []
    clicks = []
    w.edit_icon_requested.connect(lambda: edits.append(True))
    w.clicked.connect(lambda: clicks.append(True))
    _send_left_click(w, rect.center())
    assert edits == []
    assert clicks == [True]
