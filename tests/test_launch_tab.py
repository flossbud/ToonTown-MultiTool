"""LaunchTab integration: tab constructs two LaunchSection widgets and
wires the launcher buttons to launcher_runners."""
import os
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    os.environ["TTMT_NO_VENV_REEXEC"] = "1"
    app = QApplication.instance() or QApplication([])
    yield app


def _make_tab(qapp):
    from tabs.launch_tab import LaunchTab
    cred_manager = MagicMock()
    cred_manager.keyring_available = True
    cred_manager.keyring_probe_pending = False
    cred_manager.get_accounts_metadata.return_value = []
    settings_manager = MagicMock()
    settings_manager.get.return_value = None
    return LaunchTab(cred_manager=cred_manager, settings_manager=settings_manager)


def test_tab_has_two_sections(qapp):
    tab = _make_tab(qapp)
    assert tab.ttr_section is not None
    assert tab.cc_section is not None


def test_launcher_btn_invokes_runner(qapp):
    tab = _make_tab(qapp)
    with patch("tabs.launch_tab.run_official_ttr_launcher", return_value=True) as r:
        tab.ttr_section.launcher_btn.click()
    r.assert_called_once()


def test_demo_mode_populated_fills_both_sections(qapp):
    os.environ["TTMT_DEMO_LAUNCH_TAB"] = "populated"
    try:
        tab = _make_tab(qapp)
        assert len(tab.ttr_section.tiles) == 4
        assert len(tab.cc_section.tiles) == 3
    finally:
        del os.environ["TTMT_DEMO_LAUNCH_TAB"]


def test_demo_mode_empty_shows_empty_state(qapp):
    os.environ["TTMT_DEMO_LAUNCH_TAB"] = "empty"
    try:
        tab = _make_tab(qapp)
        tab.show()
        assert tab.ttr_section.empty_state.isVisible()
        assert tab.cc_section.empty_state.isVisible()
    finally:
        del os.environ["TTMT_DEMO_LAUNCH_TAB"]
