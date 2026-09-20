import pytest
from PySide6.QtWidgets import QApplication
from utils.keymap_manager import KeymapManager
from utils.widgets.keysets.split_editor import SplitEditor

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def km(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return KeymapManager()

def test_detect_visible_only_on_default_set(app, km):
    e = SplitEditor(km); e.show()
    e.set_game("ttr", default_locked=False)
    assert e._detect_btn.isVisible() is True
    assert e._delete_btn.isVisible() is False
    km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e._select(1)
    assert e._detect_btn.isVisible() is False
    assert e._delete_btn.isVisible() is True

def test_field_rows_from_actions_for(app, km):
    e = SplitEditor(km)
    e.set_game("ttr", default_locked=False)
    assert "action" in e._rows and "sprint" not in e._rows
    e.set_game("cc", default_locked=False)
    assert "sprint" in e._rows and "action" not in e._rows

def test_row_click_spotlights_key(app, km):
    e = SplitEditor(km)
    e.set_game("ttr", default_locked=False)
    e._rows["forward"]._emit_click()
    fwd_val = km.get_set("ttr", 0)["forward"]
    assert e._keyboard._caps[fwd_val].spotlight is True

def test_capture_updates_keymap(app, km):
    e = SplitEditor(km)
    e.set_game("ttr", default_locked=False)
    e._apply_capture("gags", "j")
    assert km.get_set("ttr", 0)["gags"] == "j"

def test_conflict_banner_shows(app, km):
    e = SplitEditor(km); e.show()
    e.set_game("ttr", default_locked=False)
    e._apply_capture("gags", km.get_set("ttr", 0)["forward"])
    assert e._conflict_banner.isVisible() is True


def test_title_is_inline_editor_and_pencil_enters_edit(app, km):
    from utils.widgets.keysets.inline_name_edit import InlineNameEdit
    e = SplitEditor(km); e.show()
    km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e._select(1)
    assert isinstance(e._title, InlineNameEdit)
    assert e._title.text() == km.get_set_names("ttr")[1]
    e._pencil.click()
    assert e._title.is_editing() is True


def test_commit_persists_and_updates_rail(app, km):
    e = SplitEditor(km); e.show()
    km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e._select(1)
    e._title.begin_edit()
    e._title.setText("Arrows")
    e._title._finish(commit=True)
    assert km.get_set_names("ttr")[1] == "Arrows"
    assert e._panel._items[1]._name_lbl.text() == "Arrows"
    assert e._title.text() == "Arrows"


def test_default_title_is_locked(app, km):
    e = SplitEditor(km); e.show()
    e.set_game("ttr", default_locked=False)
    assert e._title.is_locked() is True
    e._title.begin_edit()
    assert e._title.is_editing() is False


def test_begin_rename_selects_and_edits(app, km):
    e = SplitEditor(km); e.show()
    km.add_set("ttr"); km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e.begin_rename(2)
    assert e._idx == 2
    assert e._title.is_editing() is True


def test_begin_rename_on_default_only_selects(app, km):
    e = SplitEditor(km); e.show()
    km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e._select(1)
    e.begin_rename(0)
    assert e._idx == 0
    assert e._title.is_editing() is False


def test_delete_at_removes_that_set(app, km):
    e = SplitEditor(km); e.show()
    km.add_set("ttr"); km.add_set("ttr")
    e.set_game("ttr", default_locked=False)
    e._delete_at(1)
    assert km.num_sets("ttr") == 2
    assert e._idx == 1


def test_rename_dialog_is_gone(app, km):
    assert not hasattr(SplitEditor, "_rename")
