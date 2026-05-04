"""Tests for the per-slot Keep-Alive help button."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_button_has_help_accessible_metadata(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    assert btn.accessibleName() == "Keep-Alive help"
    assert "disabled" in btn.accessibleDescription().lower()
    assert "settings" in btn.accessibleDescription().lower()


def test_button_uses_pointing_hand_cursor(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    assert btn.cursor().shape() == Qt.PointingHandCursor


def test_button_has_help_tooltip(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    assert "Keep-Alive" in btn.toolTip()
    assert "disabled" in btn.toolTip().lower()


def test_button_default_size_matches_chat_button(qapp):
    """Help button is fixed 32x32 to match the per-slot chat/keep-alive
    button footprint. Any deviation would cause a layout shift on the
    visibility swap between the help and keep-alive buttons."""
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    assert btn.minimumWidth() == 32
    assert btn.maximumWidth() == 32
    assert btn.minimumHeight() == 32
    assert btn.maximumHeight() == 32


def test_button_has_help_requested_signal(qapp):
    """The signal must be a class-level Signal — connectable and emittable.

    A `hasattr` check would pass even if `help_requested` were accidentally
    declared as an instance attribute, in which case Qt silently drops
    connections at runtime. Asserting on the connect+emit round-trip is
    the only way to catch that regression.
    """
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    received = []
    btn.help_requested.connect(lambda: received.append(True))
    btn.help_requested.emit()
    assert received == [True]
