"""The Max-accounts-per-game setting was removed; ceiling is a fixed 16."""
import inspect
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

import tabs.settings_tab as st
import tabs.launch_tab as lt


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_max_per_game_ignores_stored_setting_value(qapp):
    """Behavior check: even if a legacy max_accounts_per_game value is stored,
    _max_per_game() returns the fixed ceiling of 16 (the setting is dead)."""
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = []
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: (
        4 if key == "max_accounts_per_game" else default)
    tab = lt.LaunchTab(cred_manager=cred, settings_manager=sm)
    assert tab._max_per_game() == 16


def test_settings_tab_has_no_max_accounts_signal():
    assert not hasattr(st.SettingsTab, "max_accounts_changed")
    assert not hasattr(st.SettingsTab, "_on_max_accounts_changed")


def test_launch_tab_ceiling_is_16():
    assert lt.MAX_PER_GAME == 16


def test_launch_tab_has_no_max_accounts_handler():
    assert not hasattr(lt.LaunchTab, "on_max_accounts_changed")


def test_settings_source_has_no_max_accounts_field():
    src = inspect.getsource(st)
    assert "max_accounts_per_game" not in src
    assert "Max accounts per game" not in src
