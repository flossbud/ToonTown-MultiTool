"""Tests for RacePickerDialog."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.widgets.race_picker_dialog import RacePickerDialog  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def test_renders_all_assets_as_tiles(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem=None,
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    # 20 PNGs live in assets/ccraces/
    assert len(dlg.tiles()) == 20


def test_title_shows_toon_name(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem=None,
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    assert "Flossbud" in dlg.windowTitle() or "Flossbud" in dlg.title_text()


def test_current_override_is_preselected(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem="cat",
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    assert dlg.selected_stem() == "cat"


def test_auto_marker_on_auto_stem(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem=None,
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    assert dlg.auto_marked_stem() == "dog"


def test_no_auto_marker_when_unknown_species(qt_app):
    dlg = RacePickerDialog(
        toon_name="Mystery",
        current_override_stem=None,
        auto_detected_stem=None,
        skin_color=QColor(154, 154, 154),
    )
    assert dlg.auto_marked_stem() is None


def test_save_returns_set_action(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem=None,
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    # Programmatic selection + save.
    dlg.select_stem("cat")
    dlg.accept_save()
    assert dlg.result_action() == ("set", "cat")


def test_use_auto_returns_clear_action(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem="cat",
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    dlg.accept_use_auto()
    assert dlg.result_action() == ("clear", None)


def test_cancel_returns_cancel_action(qt_app):
    dlg = RacePickerDialog(
        toon_name="Flossbud",
        current_override_stem=None,
        auto_detected_stem="dog",
        skin_color=QColor(214, 49, 49),
    )
    dlg.reject()
    assert dlg.result_action() == ("cancel", None)
