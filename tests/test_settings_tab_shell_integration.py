"""Integration tests for the rewritten SettingsTab shell — sidebar + pages."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings_manager(tmp_path):
    """A minimal in-memory SettingsManager that satisfies the .get/.set/.on_change
    contract the SettingsTab uses."""
    class _Stub:
        def __init__(self):
            self._d = {}
            self._listeners = []

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
            for fn in list(self._listeners):
                fn(key, value)

        def on_change(self, fn):
            self._listeners.append(fn)

    return _Stub()


def test_settings_tab_has_sidebar_and_four_pages(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert tab.sidebar is not None
    assert [item.key for item in tab.sidebar.items] == [
        "general", "games", "keep_alive", "advanced",
    ]
    # Each category has a page widget mounted in the content-pane stack.
    for key in ("general", "games", "keep_alive", "advanced"):
        assert key in tab.pages
        assert isinstance(tab.pages[key], QWidget)


def test_settings_tab_initial_page_persisted(qapp, settings_manager):
    settings_manager.set("settings_active_category", "keep_alive")
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert tab.sidebar.active_key == "keep_alive"
    assert tab._current_page_key == "keep_alive"


def test_settings_tab_clicking_sidebar_swaps_page_and_persists(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    # Click "games"
    tab.sidebar._on_item_clicked("games")
    assert tab._current_page_key == "games"
    assert settings_manager.get("settings_active_category") == "games"


def test_settings_tab_public_signals_exist(qapp, settings_manager):
    """All signals other modules rely on must remain on the rewritten class."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    for signal_name in (
        "debug_visibility_changed",
        "theme_changed",
        "input_backend_changed",
        "clear_credentials_requested",
        "max_accounts_changed",
    ):
        assert hasattr(tab, signal_name), f"missing signal: {signal_name}"


def test_settings_tab_public_methods_exist(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    for method_name in (
        "set_update_checker",
        "highlight_keep_alive_group",
        "get_keep_alive_delay_seconds",
        "refresh_theme",
    ):
        assert callable(getattr(tab, method_name)), f"missing method: {method_name}"


def test_settings_tab_unknown_persisted_category_falls_back_to_general(qapp, settings_manager):
    settings_manager.set("settings_active_category", "garbage_value")
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert tab.sidebar.active_key == "general"
