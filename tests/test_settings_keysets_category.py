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

def test_keysets_identity_is_yellow(app):
    assert CATEGORY_META["keysets"][0] == "#d4a017"
    assert CATEGORY_META["keysets"][1] == "#e8c14d"

def test_category_pill_colors_left_to_right(app):
    # blue, red, yellow, green, purple
    assert CATEGORY_META["general"][:2]  == ("#0077ff", "#3399ff")
    assert CATEGORY_META["games"][:2]    == ("#b34848", "#e05252")
    assert CATEGORY_META["keysets"][:2]  == ("#d4a017", "#e8c14d")
    assert CATEGORY_META["features"][:2] == ("#3da343", "#56d66a")
    assert CATEGORY_META["advanced"][:2] == ("#8B4FD6", "#a97ce6")

def test_keysets_page_is_mounted(app, km):
    from utils.widgets.keysets.keysets_page import KeysetsPage
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    assert isinstance(st.pages["keysets"], KeysetsPage)

def test_show_keysets_category_switches_stack(app, km):
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    st._show_category("keysets", animate=False)
    assert st._current_page_key == "keysets"

class _BothGamesCreds:
    def get_accounts_metadata(self, game=None): return [{"x": 1}]

def _keysets_pill(st):
    return next(p for p in st.rail.pills if p.key == "keysets")

def test_reclick_keysets_chip_returns_to_picker(app, km):
    # Drive the REAL pill-click path (not the handler directly): re-clicking the
    # already-active pill must round-trip pill -> rail.category_reselected ->
    # SettingsTab -> KeysetsPage.show_picker_if_available.
    st = SettingsTab(FakeSettings(), keymap_manager=km,
                     credentials_manager=_BothGamesCreds())
    st._show_category("keysets", animate=False)   # Keysets is the active page
    assert st.rail.active_key == "keysets"
    page = st.pages["keysets"]
    page._show_editor("ttr")                        # user drills into TTR's editor
    assert page._stack.currentIndex() == 1
    _keysets_pill(st)._activate()                   # simulate clicking the active pill
    assert page._stack.currentIndex() == 0          # back on the game picker

def test_reclick_keysets_chip_noop_without_picker(app, km):
    # Single game -> no picker; re-clicking the chip must not blow up or move.
    class _OneGameCreds:
        def get_accounts_metadata(self, game=None):
            return [{"x": 1}] if game == "ttr" else []
    st = SettingsTab(FakeSettings(), keymap_manager=km,
                     credentials_manager=_OneGameCreds())
    st._show_category("keysets", animate=False)
    page = st.pages["keysets"]
    assert page._stack.currentIndex() == 1          # straight to the TTR editor
    _keysets_pill(st)._activate()
    assert page._stack.currentIndex() == 1          # unchanged

def test_reclick_reemits_reselected_signal(app, km):
    # The rail must emit category_reselected (not swallow it) on an active
    # re-click - the exact gap the original bug hid behind.
    st = SettingsTab(FakeSettings(), keymap_manager=km, credentials_manager=FakeCreds())
    st._show_category("games", animate=False)
    got = []
    st.rail.category_reselected.connect(got.append)
    next(p for p in st.rail.pills if p.key == "games")._activate()
    assert got == ["games"]
