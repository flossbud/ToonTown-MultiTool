import pytest
from PySide6.QtWidgets import QApplication
from utils.keymap_manager import KeymapManager
from utils.widgets.keysets.keysets_page import KeysetsPage

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def _no_real_installs(monkeypatch):
    # Gate must be driven ONLY by FakeCreds accounts, never the host filesystem.
    monkeypatch.setattr("services.ttr_login_service.find_engine_path",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs",
                        lambda *a, **k: [], raising=False)

class FakeSettings:
    def __init__(self, d=None): self._d = d or {}
    def get(self, k, default=None): return self._d.get(k, default)
    def set(self, k, v): self._d[k] = v

class FakeCreds:
    def __init__(self, games=()): self._g = set(games)
    def get_accounts_metadata(self, game=None): return [{"x": 1}] if game in self._g else []

@pytest.fixture
def km(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return KeymapManager()

def _page(km, games):
    return KeysetsPage(km, FakeSettings(), FakeCreds(games))

def test_two_games_shows_picker(app, km):
    p = _page(km, ("ttr", "cc"))
    assert p._stack.currentIndex() == 0

def test_one_game_shows_editor_directly(app, km):
    p = _page(km, ("cc",))
    assert p._stack.currentIndex() == 1
    assert p.current_game() == "cc"
    assert p._back_btn.isVisible() is False

def test_zero_games_falls_back_to_ttr(app, km):
    p = _page(km, ())
    assert p._stack.currentIndex() == 1
    assert p.current_game() == "ttr"
    assert p._back_btn.isVisible() is False

def test_back_button_visible_with_two_games(app, km):
    p = _page(km, ("ttr", "cc")); p.show()
    p._show_editor("ttr")
    assert p._back_btn.isVisible() is True
