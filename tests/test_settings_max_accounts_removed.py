"""The Max-accounts-per-game setting was removed; ceiling is a fixed 16."""
import inspect
import tabs.settings_tab as st
import tabs.launch_tab as lt


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
