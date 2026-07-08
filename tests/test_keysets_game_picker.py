import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.keysets.game_picker import GamePickerView

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def test_one_card_per_game(app):
    v = GamePickerView()
    v.set_games([("ttr", 4), ("cc", 2)])
    assert set(v._cards) == {"ttr", "cc"}

def test_set_count_label(app):
    v = GamePickerView()
    v.set_games([("ttr", 4), ("cc", 2)])
    assert "4 movement sets" in v._cards["ttr"].subtitle_text()

def test_click_emits_game(app):
    v = GamePickerView()
    v.set_games([("ttr", 4), ("cc", 2)])
    got = []
    v.game_chosen.connect(got.append)
    v._cards["cc"]._emit_click()
    assert got == ["cc"]
