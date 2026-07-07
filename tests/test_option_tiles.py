"""OptionTileGrid - 2-column selectable tile grid (replaces SettingsRadioList)."""
import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.option_tiles import OptionTileGrid

ITEMS = [
    ("focused", "Focused Toon Only", "Chat affects only the toon you are playing"),
    ("all", "All Toons", "Mirror chat to every active toon"),
    ("keyset", "Keyset Dynamic", "Mirror to toons on the default keyset"),
    ("per_toon", "Per-Toon (manual)", "Pick per toon with a chat button on each card"),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_first_item_starts_selected_silently(app):
    fired = []
    grid = OptionTileGrid(ITEMS)
    grid.value_changed.connect(fired.append)
    assert grid.value() == "focused" and fired == []


def test_set_value_is_silent_and_unknown_is_noop(app):
    grid = OptionTileGrid(ITEMS)
    fired = []
    grid.value_changed.connect(fired.append)
    grid.set_value("keyset")
    assert grid.value() == "keyset" and fired == []
    grid.set_value("bogus")
    assert grid.value() == "keyset"


def test_click_emits_once(app):
    grid = OptionTileGrid(ITEMS)
    grid.apply_theme(is_dark=True, accent_key="blue")
    fired = []
    grid.value_changed.connect(fired.append)
    grid._tiles[1]._activate()
    assert grid.value() == "all" and fired == ["all"]
    grid._tiles[1]._activate()          # re-click selected: no re-emit
    assert fired == ["all"]


def test_unique_values_asserted(app):
    with pytest.raises(AssertionError):
        OptionTileGrid([("a", "A", ""), ("a", "B", "")])
