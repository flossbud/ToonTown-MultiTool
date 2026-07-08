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
