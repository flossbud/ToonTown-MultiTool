"""Tests for the extracted CC race-icon grid widget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_widget_constructs_with_tiles(qapp):
    from utils.widgets.race_icon_grid import RaceIconGridWidget
    w = RaceIconGridWidget(
        skin_color=QColor("#d9a04e"),
        selected_stem="dog",
        auto_stem="cat",
    )
    assert len(w.tiles()) > 0


def test_initial_selection_reflected(qapp):
    from utils.widgets.race_icon_grid import RaceIconGridWidget
    w = RaceIconGridWidget(QColor("#d9a04e"), "dog", "cat")
    assert w.selected_stem() == "dog"


def test_initial_selection_falls_back_to_auto(qapp):
    from utils.widgets.race_icon_grid import RaceIconGridWidget
    w = RaceIconGridWidget(QColor("#d9a04e"), None, "cat")
    assert w.selected_stem() == "cat"


def test_select_stem_emits_signal(qapp):
    from utils.widgets.race_icon_grid import RaceIconGridWidget
    w = RaceIconGridWidget(QColor("#d9a04e"), "dog", "cat")
    received: list[str] = []
    w.selection_changed.connect(received.append)
    target = next(t.stem for t in w.tiles() if t.stem != "dog")
    w.select_stem(target)
    assert w.selected_stem() == target
    assert received == [target]
