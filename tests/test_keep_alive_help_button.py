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


def test_clicking_button_creates_popover(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    # Lazy-create — popover starts None, exists after first show_popover call.
    assert btn._popover is None
    btn._ensure_popover()
    assert btn._popover is not None


def test_popover_contains_title_and_body_text(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    text = btn._popover_body_label.text() + " " + btn._popover_title_label.text()
    assert "Keep-Alive" in text
    assert "AFK" in text
    assert "Terms of Service" in text
    assert "Settings" in text


def test_popover_has_two_buttons_with_correct_labels(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    assert btn._go_to_settings_button.text() == "Go to Settings"
    assert btn._dismiss_button.text() == "Dismiss"


def test_clicking_go_to_settings_emits_help_requested(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    received = []
    btn.help_requested.connect(lambda: received.append(True))
    btn._go_to_settings_button.click()
    assert received == [True]


def test_clicking_dismiss_closes_popover_without_signal(qapp):
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    received = []
    btn.help_requested.connect(lambda: received.append(True))
    btn._dismiss_button.click()
    assert received == []


def test_ensure_popover_is_idempotent(qapp):
    """Calling _ensure_popover() twice must return the same QMenu instance —
    Task 3's lazy-create pattern is the mechanism Tasks 4-9 rely on for the
    button to be cheap to instantiate before first click."""
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    first = btn._popover
    btn._ensure_popover()
    second = btn._popover
    assert first is second


def test_refresh_theme_restyles_existing_popover(qapp):
    """If the popover has been created, refresh_theme must restyle it so a
    runtime theme toggle re-renders the popover correctly without forcing a
    re-show."""
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    sentinel_bg = "#deadbe"
    btn.refresh_theme({"bg_card": sentinel_bg})
    assert sentinel_bg.lower() in btn._popover.styleSheet().lower()


def test_clicking_dismiss_actually_closes_the_popover(qapp):
    """Tighter version of the dismiss-without-signal test: also verify the
    popover is closed, not just that no signal fired. Catches the regression
    where _on_dismiss_clicked stops calling close() on the popover."""
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    btn = KeepAliveHelpButton()
    btn._ensure_popover()
    btn._popover.show()
    btn._dismiss_button.click()
    assert not btn._popover.isVisible()


def test_popover_body_has_no_em_dashes(qapp):
    """Em-dashes have been scrubbed from user-facing strings; ensure they
    don't sneak back into the popover. Project policy: en-dash and em-dash
    are not used in messaging."""
    from tabs.multitoon._keep_alive_help_button import _POPOVER_BODY, _POPOVER_TITLE
    assert "—" not in _POPOVER_BODY, "em-dash found in popover body"
    assert "–" not in _POPOVER_BODY, "en-dash found in popover body"
    assert "—" not in _POPOVER_TITLE, "em-dash found in popover title"
    assert "–" not in _POPOVER_TITLE, "en-dash found in popover title"


def test_collapsed_ka_group_width_includes_help_button(qapp):
    """The compact-layout collapse animation's terminal width must
    accommodate BOTH chat and help buttons. Previously the formula only
    counted chat + margins, so the animation collapsed ka_group to ~40px
    while chat and help together need ~76px. Result: the two buttons
    rendered crammed together after the user toggled KA off via the UI."""
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton
    from tabs.multitoon._compact_layout import _CompactLayout

    class StubTab:
        pass

    stub_tab = StubTab()
    stub_tab.chat_buttons = []
    stub_tab.help_buttons = []
    for _ in range(4):
        cb = QPushButton()
        cb.setFixedWidth(32)
        stub_tab.chat_buttons.append(cb)
        hb = QPushButton()
        hb.setFixedWidth(32)
        stub_tab.help_buttons.append(hb)

    ka_group = QFrame()
    inner = QHBoxLayout(ka_group)
    inner.setContentsMargins(4, 4, 4, 4)
    inner.setSpacing(4)

    class StubCompact:
        pass

    stub_layout = StubCompact()
    stub_layout._tab = stub_tab
    stub_layout._card_slots = [
        {"ka_group": ka_group, "ka_group_layout": inner} for _ in range(4)
    ]

    bound = _CompactLayout._collapsed_ka_group_width.__get__(stub_layout)
    width = bound(0)
    # chat (32) + help (32) + inter-widget spacing (4) + margins (4+4 = 8) = 76
    assert width >= 76, f"collapsed ka_group width {width} cannot fit chat + help"


def test_help_button_visibility_is_inverse_of_keep_alive_widget(qapp):
    """When _reconcile_keep_alive_visibility_instant runs with master OFF,
    help buttons must be visible and KA buttons hidden; with master ON, the
    inverse. Verifies the visibility-reconciliation extension that Tasks 6-7
    rely on for the slot-layout swap to work end-to-end."""
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QPushButton, QWidget
    from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
    from tabs.multitoon._tab import MultitoonTab

    # Build a stub that has just the attributes _reconcile_keep_alive_visibility_instant
    # touches: keep_alive_buttons, ka_progress_bars, help_buttons, and _compact.
    # We avoid standing up the full MultitoonTab to keep this a unit test.
    class Stub:
        pass

    stub = Stub()
    parent = QWidget()
    stub.keep_alive_buttons = [QPushButton(parent) for _ in range(4)]
    stub.ka_progress_bars = [QWidget(parent) for _ in range(4)]
    stub.help_buttons = [KeepAliveHelpButton(parent) for _ in range(4)]
    stub._compact = MagicMock()
    stub._keep_alive_globally_enabled = lambda: False

    # Show all widgets so isHidden() reflects setVisible() state. Off-screen
    # parent suffices for offscreen QPA.
    parent.show()
    for w in stub.keep_alive_buttons + stub.ka_progress_bars + stub.help_buttons:
        w.show()

    bound = MultitoonTab._reconcile_keep_alive_visibility_instant.__get__(stub)
    bound()

    for help_btn in stub.help_buttons:
        assert not help_btn.isHidden(), "help buttons must be visible when KA master is disabled"
    for ka_btn in stub.keep_alive_buttons:
        assert ka_btn.isHidden(), "keep-alive buttons must be hidden when KA master is disabled"

    stub._keep_alive_globally_enabled = lambda: True
    bound()

    for help_btn in stub.help_buttons:
        assert help_btn.isHidden(), "help buttons must be hidden when KA master is enabled"
    for ka_btn in stub.keep_alive_buttons:
        assert not ka_btn.isHidden(), "keep-alive buttons must be visible when KA master is enabled"
