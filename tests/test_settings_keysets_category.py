import pytest
from PySide6.QtWidgets import QApplication
from utils.keymap_manager import KeymapManager
from tabs.settings_tab import SettingsTab, CATEGORY_META

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def _no_real_installs(monkeypatch):
    monkeypatch.setattr("services.ttr_login_service.find_engine_path",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs",
                        lambda *a, **k: [], raising=False)

class FakeSettings:
    def __init__(self): self._d = {}
    def get(self, k, d=None): return self._d.get(k, d)
    def set(self, k, v): self._d[k] = v
    def on_change(self, cb): pass

class FakeCreds:
    def get_accounts_metadata(self, game=None): return []

@pytest.fixture
def km(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return KeymapManager()

def test_keysets_category_registered_and_ordered(app, km):
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    keys = [k for k, _ in st.CATEGORIES]
    assert keys == ["general", "games", "keysets", "features", "advanced"]

def test_keysets_identity_is_teal(app):
    assert CATEGORY_META["keysets"][0] == "#1fb8a6"
    assert CATEGORY_META["keysets"][1] == "#4dd2c3"

def test_keysets_page_is_mounted(app, km):
    from utils.widgets.keysets.keysets_page import KeysetsPage
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    assert isinstance(st.pages["keysets"], KeysetsPage)

def test_show_keysets_category_switches_stack(app, km):
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    st._show_category("keysets", animate=False)
    assert st._current_page_key == "keysets"
