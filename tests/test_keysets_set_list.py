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


from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def _panel(app, names=("Default", "Arrows")):
    p = SetListPanel(); p.show()
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=SETS,
               set_names=list(names), selected_index=0)
    return p


def test_double_click_requests_rename_and_does_not_reselect(app):
    p = _panel(app)
    renames, selects = [], []
    p.rename_requested.connect(renames.append)
    p.set_selected.connect(selects.append)
    QTest.mouseDClick(p._items[1], Qt.LeftButton)
    assert renames == [1]
    # Qt delivers press/release/dblclick/release; the trailing release must
    # not fire a select that would rebuild the rail under the new edit.
    assert selects.count(1) <= 1


def test_double_click_on_default_requests_nothing(app):
    p = _panel(app)
    renames = []
    p.rename_requested.connect(renames.append)
    QTest.mouseDClick(p._items[0], Qt.LeftButton)
    assert renames == []


def test_context_menu_actions_for_non_default(app):
    p = _panel(app)
    menu = p._items[1]._build_menu()
    assert [a.text() for a in menu.actions()] == ["Rename", "Delete"]
    renames, deletes = [], []
    p.rename_requested.connect(renames.append)
    p.delete_requested.connect(deletes.append)
    menu.actions()[0].trigger()
    menu.actions()[1].trigger()
    assert renames == [1] and deletes == [1]


def test_no_context_menu_for_default(app):
    p = _panel(app)
    assert p._items[0]._build_menu() is None


def test_set_data_never_orphans_old_items_as_windows(app):
    p = _panel(app)
    old = list(p._items)
    p.set_data(game_short="TTR", game_accent="#4A8FE7", sets=SETS,
               set_names=["Default", "Renamed"], selected_index=1)
    for item in old:
        assert item.parent() is p and not item.isVisible()
