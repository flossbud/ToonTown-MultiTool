import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.keysets.set_list import SetListPanel

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

SETS = [{"forward": "w", "left": "a", "reverse": "s", "right": "d"},
        {"forward": "Up", "left": "Left", "reverse": "Down", "right": "Right"}]

def test_one_item_per_set(app):
    p = SetListPanel()
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=SETS,
               set_names=["Default", "Arrows"], selected_index=0)
    assert len(p._items) == 2

def test_selection_signal(app):
    p = SetListPanel()
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=SETS,
               set_names=["Default", "Arrows"], selected_index=0)
    got = []
    p.set_selected.connect(got.append)
    p._items[1]._emit_click()
    assert got == [1]

def test_add_hidden_at_max(app):
    p = SetListPanel()
    eight = [dict(SETS[0]) for _ in range(8)]
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=eight,
               set_names=[f"S{i}" for i in range(8)], selected_index=0)
    assert p._add_btn.isVisible() is False

def test_add_signal(app):
    p = SetListPanel()
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=SETS,
               set_names=["Default", "Arrows"], selected_index=0)
    got = []
    p.add_requested.connect(lambda: got.append(True))
    p._add_btn.click()
    assert got == [True]
