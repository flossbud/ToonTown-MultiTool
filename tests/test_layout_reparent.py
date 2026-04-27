"""Regression test for the multitoon-full-ui shared-widget reparenting bug.

The Compact and Full layouts both consume the same per-slot widget instances
(portrait, name label, enable button, etc.). When set_layout_mode swaps between
them, each layout's populate() must re-add the widgets so they end up parented
under the visible layout. If populate is broken, Full UI renders empty.

Run via pytest with QT_QPA_PLATFORM=offscreen (set in fixture if needed)."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettingsManager:
    """Minimal stand-in for SettingsManager — supports .get() and .on_change()
    enough for MultitoonTab.build_ui to succeed in tests."""

    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        # We don't need to actually invoke the callback in tests.
        pass


class _FakeWindowManager(QObject):
    """Minimal stand-in for WindowManager — provides the signals and attributes
    that MultitoonTab.__init__ and visual-state methods access."""

    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


@pytest.fixture
def tab(qapp):
    """A fully-built MultitoonTab with fake managers — safe for offscreen."""
    from tabs.multitoon_tab import MultitoonTab
    return MultitoonTab(
        settings_manager=_FakeSettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def _is_descendant_of(widget, ancestor) -> bool:
    """True if ancestor is somewhere in widget's parent chain."""
    cur = widget.parent() if widget is not None else None
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parent()
    return False


def test_compact_owns_shared_widgets_at_startup(tab):
    assert tab._mode == "compact"

    # Toggle service button should be parented somewhere under _compact
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    # And NOT under _full (Full's items, if any, must be stale)
    assert not _is_descendant_of(tab.toggle_service_button, tab._full)

    # Each per-slot shared widget should also live under _compact
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact), (
            f"slot {i} toon_button should be under _compact"
        )
        assert _is_descendant_of(tab.set_selectors[i], tab._compact)


def test_swap_to_full_reparents_shared_widgets(tab):
    tab.set_layout_mode("full")
    assert tab._mode == "full"

    # toggle_service_button must move under _full (the service-bar row)
    assert _is_descendant_of(tab.toggle_service_button, tab._full)
    # And no longer under _compact
    assert not _is_descendant_of(tab.toggle_service_button, tab._compact)

    # Per-slot widgets should now live under _full
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._full), (
            f"slot {i} toon_button should be under _full after swap"
        )
        assert _is_descendant_of(tab.slot_badges[i], tab._full)


def test_swap_back_to_compact_reparents_again(tab):
    tab.set_layout_mode("full")
    tab.set_layout_mode("compact")
    assert tab._mode == "compact"

    # Widgets should now live under _compact again
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    assert not _is_descendant_of(tab.toggle_service_button, tab._full)
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)


def test_set_layout_mode_idempotent(tab):
    """Calling set_layout_mode with the current mode should be a no-op."""
    tab.set_layout_mode("compact")  # already compact
    assert tab._mode == "compact"
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)


def test_full_to_compact_roundtrip_restores_shared_widget_sizes(tab):
    """After Full → Compact, shared widgets must be back to Compact's defaults
    (selector 28px tall, ka_bar elastic, no leftover padding-right on name)."""
    # Initial state: Compact defaults
    assert tab.set_selectors[0].height() <= 28 or tab.set_selectors[0].maximumHeight() == 28

    tab.set_layout_mode("full")
    # Full mutates: selector becomes 44, ka_bar fixed-size, name padding-right
    assert tab.set_selectors[0].maximumHeight() == 44

    tab.set_layout_mode("compact")
    # Compact must restore defaults
    assert tab.set_selectors[0].maximumHeight() == 28, (
        f"selector height should reset to 28 after roundtrip; got {tab.set_selectors[0].maximumHeight()}"
    )
    # ka_bar: maximumWidth should be unconstrained (16777215 is QWIDGETSIZE_MAX)
    assert tab.ka_progress_bars[0].maximumWidth() >= 16777215, (
        f"ka_bar width should be elastic after roundtrip; got max width {tab.ka_progress_bars[0].maximumWidth()}"
    )
    # name_label stylesheet should not contain accumulated padding stanzas
    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    assert sheet.count("padding-right") <= 1, (
        f"padding-right should not accumulate; sheet={sheet!r}"
    )


def test_apply_visual_state_propagates_to_full_card(tab):
    """Critical bug regression: Full UI cards' active state must mirror window availability."""
    # Initial: no windows detected → all cards inactive
    for card in tab._full._cards:
        assert card._is_active is False

    # Simulate a game window arriving for slot 0
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.apply_visual_state(0)

    # Slot 0's Full card should now be active; others remain inactive
    assert tab._full._cards[0]._is_active is True, (
        "Full card 0 should reflect window availability after apply_visual_state"
    )
    for i in range(1, 4):
        assert tab._full._cards[i]._is_active is False


def test_full_name_label_styling_survives_refresh_theme(tab):
    """Critical bug regression: refresh_theme must not wipe Full UI's name styling."""
    tab.set_layout_mode("full")
    tab.refresh_theme()  # explicit second pass — must not break Full styling

    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    # Full UI requires 26px font-size and right padding for the game pill.
    assert "font-size: 26px" in sheet, f"Full name-label should be 26px; got {sheet!r}"
    assert "padding-right: 60px" in sheet, (
        f"Full name-label should reserve 60px for game pill; got {sheet!r}"
    )


def test_full_stats_labels_get_scaled_font(tab):
    """Stats labels (LAFF/beans) must get Full UI's 17px override, not
    compact's 13px, after refresh_theme + Full apply_theme."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    for label_list in (tab.laff_labels, tab.bean_labels):
        sheet = label_list[0].styleSheet()
        assert "font-size: 17px" in sheet, (
            f"Full stats label should be 17px; got {sheet!r}"
        )


def test_compact_startup_uses_original_widget_sizes(tab):
    """Regression: at startup, shared widgets must keep their constructor-time
    constraints in Compact mode. _FullLayout.populate_active runs during init
    and mutates badge → 104x104 and ka_bar → 90x8; Compact's populate must
    restore the original 38-64 badge bounds and 7px-tall ka_bar."""
    # Badge: ToonPortraitWidget defaults are setMinimumSize(38, 38) + setMaximumSize(64, 64)
    badge = tab.slot_badges[0]
    assert badge.minimumSize().width() == 38 and badge.minimumSize().height() == 38, (
        f"badge min should be (38, 38); got {badge.minimumSize()}"
    )
    assert badge.maximumSize().width() == 64 and badge.maximumSize().height() == 64, (
        f"badge max should be (64, 64); got {badge.maximumSize()}"
    )
    # ka_bar: SmoothProgressBar defaults are setFixedHeight(7) + setMinimumWidth(40)
    ka_bar = tab.ka_progress_bars[0]
    assert ka_bar.minimumWidth() == 40, (
        f"ka_bar min width should be 40; got {ka_bar.minimumWidth()}"
    )
    assert ka_bar.maximumHeight() == 7, (
        f"ka_bar should be fixed at 7px tall; got max height {ka_bar.maximumHeight()}"
    )


def test_full_card_content_packs_at_top_in_tall_card(qapp, tab):
    """Regression: the Full UI card's active grid must use `align-content: start`
    semantics — content packed at top with empty space below — so when cards
    expand to fill a tall window, the portrait stays anchored next to the
    name/stats instead of getting stranded above huge gaps.

    Verifies _active_root has Maximum vertical size policy so it renders at
    its content height (~140px) instead of stretching to fill the card.
    """
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QSizePolicy, QWidget, QVBoxLayout

    tab.set_layout_mode("full")
    tab._full._cards[0].set_active(True)

    # Show stats so the card content is at its production height
    name_label, _ = tab.toon_labels[0]
    name_label.setText("Royal Blue Bear")
    tab.laff_labels[0].setText(" 15/15"); tab.laff_labels[0].show()
    tab.bean_labels[0].setText(" 10,935"); tab.bean_labels[0].show()

    host = QWidget(); v = QVBoxLayout(host); v.setContentsMargins(0, 0, 0, 0); v.addWidget(tab)
    host.resize(QSize(1280, 800))
    host.show()
    for _ in range(10):
        qapp.processEvents()

    card = tab._full._cards[0]
    assert card._active_root.sizePolicy().verticalPolicy() == QSizePolicy.Maximum, (
        "active_root must have Maximum vertical size policy so it does not "
        "stretch to fill the card height"
    )
    # active_root sized at ~140px (portrait + controls); card is 280-310px in
    # this layout. The empty space difference must go BELOW the active_root.
    empty_below = card.height() - (card._active_root.y() + card._active_root.height())
    assert empty_below > 50, (
        f"Expected empty space (>50px) below active_root, got {empty_below}px. "
        f"Card height={card.height()}, active_root height={card._active_root.height()}"
    )


def test_game_pill_parented_to_card_not_active_root(tab):
    """The game pill must be a child of the card frame, not _active_root,
    so resizeEvent's self.width()-based positioning is in the right
    coordinate space."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    pill = card._game_pill
    assert pill is not None, "game_pill should be set after populate_active"
    assert pill.parent() is card, (
        f"game_pill should be parented to card, not {pill.parent().__class__.__name__}"
    )


def test_full_portrait_and_controls_scaled(tab):
    """Full UI portrait must be 156x156 and controls 44px tall."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]

    assert card._portrait_wrap.width() == 156, (
        f"portrait wrapper should be 156px wide; got {card._portrait_wrap.width()}"
    )
    assert card._portrait_wrap.height() == 156, (
        f"portrait wrapper should be 156px tall; got {card._portrait_wrap.height()}"
    )

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 44, (
        f"enable button should be 44px tall; got max height {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 110, (
        f"enable button should be 110px wide; got max width {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 44, (
        f"chat button should be 44px tall; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 44, (
        f"chat button should be 44px wide; got {chat.maximumWidth()}"
    )

    ka_bar = tab.ka_progress_bars[0]
    assert ka_bar.maximumWidth() == 140, (
        f"ka progress bar should be 140px wide; got {ka_bar.maximumWidth()}"
    )
    assert ka_bar.maximumHeight() == 12, (
        f"ka progress bar should be 12px tall; got {ka_bar.maximumHeight()}"
    )


def test_full_to_compact_roundtrip_restores_button_sizes(tab):
    """After Full → Compact, buttons must reset to Compact's creation defaults."""
    tab.set_layout_mode("full")
    assert tab.toon_buttons[0].maximumHeight() == 44

    tab.set_layout_mode("compact")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 32, (
        f"enable button height should reset to 32; got {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 88, (
        f"enable button width should reset to 88; got {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 32, (
        f"chat button height should reset to 32; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 32, (
        f"chat button width should reset to 32; got {chat.maximumWidth()}"
    )

    ka = tab.keep_alive_buttons[0]
    assert ka.maximumHeight() == 32, (
        f"KA button height should reset to 32; got {ka.maximumHeight()}"
    )
    assert ka.maximumWidth() == 32, (
        f"KA button width should reset to 32; got {ka.maximumWidth()}"
    )


def test_pulse_anim_stops_when_leaving_full(tab):
    """Important bug regression: pulse animations must not keep running in Compact."""
    # Activate slot 0 so its pulse starts in Full
    tab.set_layout_mode("full")
    tab.window_manager.ttr_window_ids = ["fake-id"]
    tab.apply_visual_state(0)
    assert tab._full._cards[0]._is_active is True
    # Pulse may or may not be running depending on disable_animations; if it is,
    # leaving Full must stop it.
    pulse_was_running = tab._full._cards[0]._pulse_anim is not None

    tab.set_layout_mode("compact")
    # After leaving Full, no card should have a live pulse
    for card in tab._full._cards:
        assert card._pulse_anim is None, (
            f"Pulse anim should stop on swap to Compact; was_running={pulse_was_running}"
        )
