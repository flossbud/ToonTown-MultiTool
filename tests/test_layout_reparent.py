"""Regression test for the multitoon-full-ui shared-widget reparenting bug.

The Compact and Full layouts both consume the same per-slot widget instances
(portrait, name label, enable button, etc.). When set_layout_mode swaps between
them, each layout's populate() must re-add the widgets so they end up parented
under the visible layout. If populate is broken, Full UI renders empty.

Run via pytest with QT_QPA_PLATFORM=offscreen (set in fixture if needed)."""

import os
import threading
import time
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

    # ServiceStatusBar (Compact's service UI) lives under _compact.
    assert _is_descendant_of(tab.service_status_bar, tab._compact)
    assert not _is_descendant_of(tab.service_status_bar, tab._full)

    # Each per-slot shared widget should also live under _compact
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact), (
            f"slot {i} toon_button should be under _compact"
        )
        assert _is_descendant_of(tab.set_selectors[i], tab._compact)


def test_swap_to_full_reparents_shared_widgets(tab):
    tab.set_layout_mode("full")
    assert tab._mode == "full"

    # Per-slot widgets should now live under _full
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._full), (
            f"slot {i} toon_button should be under _full after swap"
        )
        assert _is_descendant_of(tab.slot_badges[i], tab._full)


def test_config_label_reparented_to_full(tab):
    """Config label must be a descendant of _full in full mode."""
    tab.set_layout_mode("full")
    assert _is_descendant_of(tab.config_label, tab._full), (
        "config_label should be under _full in full mode"
    )
    assert not _is_descendant_of(tab.config_label, tab._compact), (
        "config_label should NOT be under _compact in full mode"
    )

    tab.set_layout_mode("compact")
    assert _is_descendant_of(tab.config_label, tab._compact), (
        "config_label should be under _compact after swap back"
    )


def test_swap_back_to_compact_reparents_again(tab):
    # In compact mode, service_status_bar lives under compact
    assert _is_descendant_of(tab.service_status_bar, tab._compact)

    tab.set_layout_mode("full")
    # In full mode, service_status_bar moves to full
    assert _is_descendant_of(tab.service_status_bar, tab._full)

    tab.set_layout_mode("compact")
    assert tab._mode == "compact"

    # Back in compact: service_status_bar is under compact again
    assert _is_descendant_of(tab.service_status_bar, tab._compact)
    assert not _is_descendant_of(tab.service_status_bar, tab._full)

    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)


def test_prewarm_full_layout_restores_compact_ownership(qapp, tab):
    """Hidden Full warmup must not visibly switch modes or steal widgets."""
    tab.prewarm_full_layout()
    qapp.processEvents()

    assert tab._mode == "compact"
    assert tab._stack.currentWidget() is tab._compact
    assert "inactive" in tab._full_layout_prewarmed_states
    # service_status_bar (Compact's service UI) must remain under compact after prewarm
    assert _is_descendant_of(tab.service_status_bar, tab._compact)
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)
        assert _is_descendant_of(tab.slot_badges[i], tab._compact)


def test_prewarm_full_layout_can_warm_active_cards(qapp, tab):
    """Service-start warmup should cover the active-card path too."""
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.service_running = True
    tab.enabled_toons[0] = True

    tab.prewarm_full_layout(include_active=True)
    qapp.processEvents()

    assert tab._mode == "compact"
    assert "active" in tab._full_layout_prewarmed_states
    assert _is_descendant_of(tab.toon_buttons[0], tab._compact)
    assert _is_descendant_of(tab.slot_badges[0], tab._compact)


def test_automatic_prewarm_skips_active_cards(qapp, tab):
    """Automatic warmups must not block the first service-start toon click."""
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.service_running = True
    tab.enabled_toons[0] = True

    tab.prewarm_full_layout()
    qapp.processEvents()

    assert tab._mode == "compact"
    assert not hasattr(tab, "_full_layout_prewarmed_states")
    assert _is_descendant_of(tab.toon_buttons[0], tab._compact)


def test_duplicate_toon_data_fetch_is_deduped(monkeypatch, tab):
    """Service start and window update can ask for the same toon data at once."""
    from tabs.multitoon import _tab as multitoon_tab
    from utils.game_registry import GameRegistry

    calls = []
    release = threading.Event()

    def fake_get_toon_names_by_slot(num_slots, current_window_ids=None):
        calls.append((num_slots, list(current_window_ids or [])))
        assert release.wait(timeout=2.0)
        return (
            ["Toon A", "Toon B"],
            ["dna-a", "dna-b"],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
        )

    monkeypatch.setattr(multitoon_tab, "get_toon_names_by_slot", fake_get_toon_names_by_slot)
    monkeypatch.setattr(
        GameRegistry.instance(),
        "get_game_for_window",
        lambda wid: "ttr",
    )

    tab.window_manager.ttr_window_ids = ["wid-1", "wid-2"]

    tab._fetch_names_if_enabled(2)
    deadline = time.monotonic() + 1.0
    while len(calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    tab._fetch_names_if_enabled(2)

    assert len(calls) == 1

    release.set()
    deadline = time.monotonic() + 1.0
    while tab._toon_fetch_inflight_keys and time.monotonic() < deadline:
        time.sleep(0.01)

    tab._fetch_names_if_enabled(2)
    assert len(calls) == 2


def test_scheduled_toon_data_fetch_coalesces(qapp, monkeypatch, tab):
    calls = []
    tab.window_manager.ttr_window_ids = ["wid-1", "wid-2"]

    def fake_fetch(num_slots):
        calls.append(num_slots)

    monkeypatch.setattr(tab, "_fetch_names_if_enabled", fake_fetch)

    tab.schedule_toon_data_fetch(0)
    tab.schedule_toon_data_fetch(0)
    qapp.processEvents()

    assert calls == [2]


def test_set_layout_mode_idempotent(tab):
    """Calling set_layout_mode with the current mode should be a no-op."""
    tab.set_layout_mode("compact")  # already compact
    assert tab._mode == "compact"
    # service_status_bar owns compact's service row
    assert _is_descendant_of(tab.service_status_bar, tab._compact)


def test_set_layout_mode_flips_mode_before_setCurrentWidget(tab):
    """Regression: _mode must be flipped BEFORE setCurrentWidget so Qt's resize
    cascade during the swap routes through the new mode's gates."""
    captured = []
    orig = tab._stack.setCurrentWidget

    def spy(target):
        captured.append(tab._mode)
        return orig(target)

    tab._stack.setCurrentWidget = spy
    try:
        tab.set_layout_mode("full")
        assert captured[-1] == "full", (
            f"_mode should be 'full' when setCurrentWidget runs; got {captured[-1]}"
        )

        tab.set_layout_mode("compact")
        assert captured[-1] == "compact", (
            f"_mode should be 'compact' when setCurrentWidget runs; got {captured[-1]}"
        )
    finally:
        tab._stack.setCurrentWidget = orig


def test_full_to_compact_roundtrip_restores_shared_widget_sizes(tab):
    """After Full -> Compact, shared widgets must be back to Compact's defaults
    (selector 28px tall, ka_bar elastic, no leftover padding-right on name)."""
    # Initial state: Compact defaults
    assert tab.set_selectors[0].maximumHeight() == 28

    tab.set_layout_mode("full")
    # Full mode uses compact's same sizing (compact-clone refactor)
    assert tab.set_selectors[0].maximumHeight() == 28

    tab.set_layout_mode("compact")
    # Compact must keep defaults
    assert tab.set_selectors[0].maximumHeight() == 28, (
        f"selector height should remain 28; got {tab.set_selectors[0].maximumHeight()}"
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


def test_compact_visual_state_does_not_apply_full_scaling(tab):
    """Service/window updates in Compact must not let hidden Full cards resize shared widgets."""
    assert tab._mode == "compact"
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.input_service = object()
    tab.service_running = True
    tab.enabled_toons[0] = True

    tab.apply_visual_state(0)

    assert tab.toon_buttons[0].maximumHeight() == 32
    assert tab.toon_buttons[0].maximumWidth() == 88
    assert tab.chat_buttons[0].maximumHeight() == 32
    assert tab.chat_buttons[0].maximumWidth() == 32
    assert tab.keep_alive_buttons[0].maximumHeight() == 32
    assert tab.keep_alive_buttons[0].maximumWidth() == 32
    assert tab.ka_progress_bars[0].maximumHeight() == 7
    assert tab.ka_progress_bars[0].maximumWidth() >= 16777215
    assert tab.set_selectors[0].maximumHeight() == 28


def test_stats_labels_keep_icons_in_full_mode(tab):
    """Full should not alternate between icon stats and LAFF/JB text labels."""
    tab.set_layout_mode("full")
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab._last_window_ids = ["fake-window-id"]
    tab.toon_names[0] = "Mint"
    tab.toon_laffs[0] = 16
    tab.toon_max_laffs[0] = 16
    tab.toon_beans[0] = 10306

    tab._refresh_toon_stats_labels()

    assert tab.laff_labels[0].text() == " 16/16"
    assert tab.bean_labels[0].text() == " 10,306"
    assert not tab.laff_labels[0].icon().isNull()
    assert not tab.bean_labels[0].icon().isNull()


def test_compact_startup_uses_original_widget_sizes(tab):
    """Regression: at startup, shared widgets must keep Compact's expected
    constraints. Compact sets the badge to 64x64 in Direction D design."""
    badge = tab.slot_badges[0]
    assert badge.minimumSize().width() == 64 and badge.minimumSize().height() == 64, (
        f"badge min should be (64, 64); got {badge.minimumSize()}"
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


def test_full_layout_uses_full_surface_colors(tab):
    """Full Multitoon card surfaces use bg_card and border_card from the theme."""
    tab.set_layout_mode("full")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab._full._card_slots[0]["card"].styleSheet()
    assert c["bg_card"] in card_sheet
    assert c["border_card"] in card_sheet


def test_compact_light_layout_uses_full_card_surface_colors(tab):
    """Compact light mode: Direction D brand-stripe chrome uses bg_card as
    the card background in both light and dark modes. Empty slots get a
    dashed border using border_light."""
    tab.settings_manager.set("theme", "light")
    tab.set_layout_mode("compact")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab.toon_cards[0].styleSheet()
    # Direction D always uses bg_card as the card background surface
    assert c["bg_card"] in card_sheet, (
        f"light card should use bg_card ({c['bg_card']}); got {card_sheet!r}"
    )
    # The old inner-card surface token must not appear (it's for ka_group insets)
    assert c["bg_card_inner"] not in card_sheet, (
        f"light card should not use bg_card_inner; got {card_sheet!r}"
    )


def test_compact_dark_layout_keeps_original_card_surface_colors(tab):
    """Dark mode: Direction D brand-stripe chrome uses bg_card as the card
    background. The old bg_card_inner token is for ka_group insets, not cards."""
    tab.settings_manager.set("theme", "dark")
    tab.set_layout_mode("compact")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab.toon_cards[0].styleSheet()
    # Direction D always uses bg_card as the card background surface
    assert c["bg_card"] in card_sheet, (
        f"dark card should use bg_card ({c['bg_card']}); got {card_sheet!r}"
    )
    # The old bg_card_inner and border_muted tokens are for ka_group insets
    assert c["bg_card_inner"] not in card_sheet, (
        f"dark card should not use bg_card_inner; got {card_sheet!r}"
    )


def test_full_to_compact_roundtrip_restores_button_sizes(tab):
    """After Full -> Compact, buttons must reset to Compact's creation defaults."""
    tab.set_layout_mode("full")
    # Full mode uses compact-clone sizing — same as compact
    assert tab.toon_buttons[0].maximumHeight() == 32

    tab.set_layout_mode("compact")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 32, (
        f"enable button height should be 32; got {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 88, (
        f"enable button width should be 88; got {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 32, (
        f"chat button height should be 32; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 32, (
        f"chat button width should be 32; got {chat.maximumWidth()}"
    )

    ka = tab.keep_alive_buttons[0]
    assert ka.maximumHeight() == 32, (
        f"KA button height should be 32; got {ka.maximumHeight()}"
    )
    assert ka.maximumWidth() == 32, (
        f"KA button width should be 32; got {ka.maximumWidth()}"
    )


def test_toggle_keep_alive_refreshes_status_dot_to_orange_pulse(qapp, tab):
    """Toggling keep-alive on a disabled-but-detected toon must flip the status
    dot to the keep_alive state (orange + pulsing).

    Regression: the widget-build refactor dropped apply_visual_state(index) from
    toggle_keep_alive, so the dot stayed in its previous state after the toggle.
    """
    # Slot 0: window detected, toon disabled. Establish baseline state.
    # The master Keep-Alive flag must be on for toggle_keep_alive to take effect
    # (it now early-returns when the global setting is off).
    tab.settings_manager.set("keep_alive_enabled", True)
    tab.input_service = object()
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.enabled_toons[0] = False
    tab.apply_visual_state(0)
    qapp.processEvents()

    _, status_dot = tab.toon_labels[0]
    assert not status_dot._pulsing, "baseline disabled dot should not pulse"

    # Now flip keep-alive on. Dot should become keep_alive (orange + pulsing).
    tab.toggle_keep_alive(0)
    qapp.processEvents()

    assert status_dot._pulsing, "status dot should pulse when keep-alive is on"
    assert status_dot._color.name() == "#ff9900", (
        f"status dot should be orange (#ff9900) for keep_alive state; got {status_dot._color.name()}"
    )
