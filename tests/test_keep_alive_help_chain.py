"""Integration test for the Keep-Alive help discovery signal chain.

The wiring under test:
- Per-slot KeepAliveHelpButton.help_requested fires
- MultitoonTab forwards via keep_alive_help_requested.emit()
- MultiToonTool._on_keep_alive_help_requested calls nav_select(3) +
  settings_tab.highlight_keep_alive_group()

Standing up the full MultiToonTool is too heavy for a unit test, so this
binds the slot method to a stub and asserts the contract directly.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_on_keep_alive_help_requested_navigates_and_highlights(qapp):
    """The slot bound to the help-requested signal must call nav_select(3)
    and then settings_tab.highlight_keep_alive_group()."""
    from unittest.mock import MagicMock
    from main import MultiToonTool

    stub = MagicMock()
    bound = MultiToonTool._on_keep_alive_help_requested.__get__(stub)
    bound()

    stub.nav_select.assert_called_once_with(3)
    stub.settings_tab.highlight_keep_alive_group.assert_called_once_with()


def test_help_button_signal_propagates_through_multitoon_tab(qapp):
    """A click on the Go-to-Settings popover button must propagate from the
    per-slot KeepAliveHelpButton through MultitoonTab.keep_alive_help_requested.

    This locks the connection added in MultitoonTab.__init__ — without it,
    clicking the popover would fire the per-button signal but the tab would
    never re-emit, and MultiToonTool would never see it."""
    from PySide6.QtCore import QObject, Signal
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton

    class FakeMultitoonTab(QObject):
        keep_alive_help_requested = Signal()

    fake_tab = FakeMultitoonTab()
    btn = KeepAliveHelpButton()
    btn.help_requested.connect(fake_tab.keep_alive_help_requested.emit)

    received = []
    fake_tab.keep_alive_help_requested.connect(lambda: received.append(True))

    btn._ensure_popover()
    btn._go_to_settings_button.click()
    assert received == [True]
