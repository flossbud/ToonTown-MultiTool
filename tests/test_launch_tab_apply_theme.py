# tests/test_launch_tab_apply_theme.py
"""Verify LaunchTab.refresh_theme() propagates the theme dict to every
styled child: TTR/CC sections and the (single, optional) keyring banner."""
from unittest.mock import MagicMock
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build_tab(qapp):
    """LaunchTab needs a settings_manager + cred_manager + logger. Mock all three
    so the test does not load the user's real credentials file or hit the system
    keyring."""
    from tabs.launch_tab import LaunchTab
    sm = MagicMock()
    sm.get = MagicMock(return_value="dark")
    sm.get_accounts = MagicMock(return_value={"ttr": [], "cc": []})
    cred_manager = MagicMock()
    cred_manager.keyring_probe_pending = False
    cred_manager.keyring_available = True
    cred_manager.get_accounts_metadata = MagicMock(return_value=[])
    cred_manager._legacy_fallback_deleted = False
    logger = MagicMock()
    return LaunchTab(settings_manager=sm, cred_manager=cred_manager, logger=logger)


def test_refresh_theme_propagates_to_sections(qapp):
    tab = _build_tab(qapp)
    spy_ttr = MagicMock(wraps=tab.ttr_section.apply_theme)
    spy_cc = MagicMock(wraps=tab.cc_section.apply_theme)
    tab.ttr_section.apply_theme = spy_ttr
    tab.cc_section.apply_theme = spy_cc
    tab.refresh_theme()
    assert spy_ttr.called, "TTR section did not receive apply_theme"
    assert spy_cc.called, "CC section did not receive apply_theme"


def test_refresh_theme_propagates_to_keyring_banner_if_present(qapp):
    """If a keyring banner is currently rendered, it must receive
    apply_theme."""
    from tabs.launch_tab import KeyringPendingBanner
    tab = _build_tab(qapp)
    # Force a banner into place for the test.
    tab._keyring_banner = KeyringPendingBanner(parent=tab)
    spy = MagicMock(wraps=tab._keyring_banner.apply_theme)
    tab._keyring_banner.apply_theme = spy
    tab.refresh_theme()
    assert spy.called, "keyring banner did not receive apply_theme"


def test_refresh_theme_handles_no_banner(qapp):
    """When self._keyring_banner is None (the normal state), refresh_theme
    must not raise AND must still propagate to the sections."""
    tab = _build_tab(qapp)
    tab._keyring_banner = None
    spy_ttr = MagicMock(wraps=tab.ttr_section.apply_theme)
    spy_cc = MagicMock(wraps=tab.cc_section.apply_theme)
    tab.ttr_section.apply_theme = spy_ttr
    tab.cc_section.apply_theme = spy_cc
    tab.refresh_theme()  # must not raise
    assert spy_ttr.called, "TTR section must receive apply_theme even when banner is None"
    assert spy_cc.called, "CC section must receive apply_theme even when banner is None"
