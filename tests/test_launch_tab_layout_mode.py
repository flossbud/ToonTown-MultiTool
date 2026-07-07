"""LaunchTab participates in the app-wide compact<->full layout mode."""
import pytest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_launch_tab(qapp):
    """Mirrors tests/test_launch_tab.py:_make_tab -- uses get_accounts_metadata
    (not get_accounts) and settings.get.return_value (not side_effect)."""
    from tabs.launch_tab import LaunchTab
    from unittest.mock import MagicMock
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    return tab


def test_launch_tab_has_set_layout_mode(qapp):
    tab = _make_launch_tab(qapp)
    assert hasattr(tab, "set_layout_mode")


def test_launch_tab_full_mode_places_sections_side_by_side(qapp):
    tab = _make_launch_tab(qapp)
    tab.set_layout_mode("full")
    ttr_parent = tab.ttr_section.parentWidget()
    cc_parent = tab.cc_section.parentWidget()
    assert ttr_parent is cc_parent
    parent_layout = ttr_parent.layout()
    assert isinstance(parent_layout, QHBoxLayout)


def test_launch_tab_compact_mode_stacks_sections(qapp):
    tab = _make_launch_tab(qapp)
    tab.set_layout_mode("full")
    tab.set_layout_mode("compact")
    ttr_parent_layout = tab.ttr_section.parentWidget().layout()
    cc_parent_layout = tab.cc_section.parentWidget().layout()
    assert isinstance(ttr_parent_layout, QVBoxLayout)
    assert isinstance(cc_parent_layout, QVBoxLayout)


def test_launch_tab_set_layout_mode_propagates_to_sections(qapp):
    tab = _make_launch_tab(qapp)
    tab.set_layout_mode("full")
    assert tab.ttr_section.maximumWidth() == 860
    assert tab.cc_section.maximumWidth() == 860
    tab.set_layout_mode("compact")
    assert tab.ttr_section.maximumWidth() == 740
    assert tab.cc_section.maximumWidth() == 740
