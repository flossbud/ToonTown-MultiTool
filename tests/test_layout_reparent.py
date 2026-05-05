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
    tab.set_layout_mode("full")
    tab.set_layout_mode("compact")
    assert tab._mode == "compact"

    # Widgets should now live under _compact again
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    assert not _is_descendant_of(tab.toggle_service_button, tab._full)
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)


def test_prewarm_full_layout_restores_compact_ownership(qapp, tab):
    """Hidden Full warmup must not visibly switch modes or steal widgets."""
    tab.prewarm_full_layout()
    qapp.processEvents()

    assert tab._mode == "compact"
    assert tab._stack.currentWidget() is tab._compact
    assert "inactive" in tab._full_layout_prewarmed_states
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)
        assert _is_descendant_of(tab.slot_badges[i], tab._compact)


def test_position_cards_skips_label_when_reparented_to_compact(qapp, tab):
    """Regression: TOON CONFIGURATION label rendered at y=0 above Start Service.

    _FullLayout.resize() queues _position_cards via QTimer.singleShot(0, ...)
    so tests / hidden-widget callers can still trigger card positioning. During
    prewarm_full_layout, _full.resize(warm_size) queues that timer; the prewarm
    finally block then calls _compact.populate(), which reparents config_label
    back to outer_card. When the queued timer fires AFTER prewarm returns,
    _position_cards still calls setGeometry(ox, oy, grid_w, label_h) on
    config_label — but the label is now in compact's layout, so the geometry
    clobbers compact's layout-managed position, leaving the label at y=0 with
    full-grid width above the Start Service button.

    Guard: _position_cards must skip the config_label setGeometry when
    config_label is no longer parented to _grid_container.
    """
    # Run prewarm so _grid_container ends up with real width/height that
    # _position_cards would otherwise act on.
    tab.prewarm_full_layout()
    qapp.processEvents()
    assert tab._mode == "compact"
    assert tab.config_label.parentWidget() is tab.outer_card, (
        "precondition: compact.populate should have reclaimed config_label"
    )

    # Realize compact's layout so config_label sits where compact wants it
    # (below the Start Service button + status bar + divider).
    tab.resize(720, 800)
    tab.show()
    qapp.processEvents()
    expected_geom = tab.config_label.geometry()
    assert expected_geom.y() > tab.toggle_service_button.y(), (
        f"sanity: compact should put config_label below the Start Service "
        f"button; got cfg.y={expected_geom.y()}, btn.y={tab.toggle_service_button.y()}"
    )

    # Simulate the queued QTimer firing _position_cards after compact has
    # reclaimed the label. This MUST NOT touch config_label's geometry.
    tab._full._position_cards()

    assert tab.config_label.geometry() == expected_geom, (
        f"_position_cards clobbered compact-layout-managed config_label geometry: "
        f"expected {expected_geom.getRect()}, got {tab.config_label.geometry().getRect()}"
    )


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
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)


def test_set_layout_mode_flips_mode_before_setCurrentWidget(tab):
    """Regression: _mode must be flipped BEFORE setCurrentWidget so Qt's resize
    cascade during the swap routes through the new mode's gates. If _mode flips
    after, _FullToonCard._layout_active_content's mode gate causes the cascade
    to skip scale recompute, leaving Full's content rendered at a stale small
    scale after a window minimize/restore cycle (visible as 'tiny content')."""
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
    """After Full → Compact, shared widgets must be back to Compact's defaults
    (selector 28px tall, ka_bar elastic, no leftover padding-right on name)."""
    # Initial state: Compact defaults
    assert tab.set_selectors[0].height() <= 28 or tab.set_selectors[0].maximumHeight() == 28

    tab.set_layout_mode("full")
    # Full mutates: selector becomes the reference design-surface size.
    assert tab.set_selectors[0].maximumHeight() == 36

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
    tab.set_layout_mode("full")
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


def test_full_name_label_styling_survives_refresh_theme(tab):
    """Critical bug regression: refresh_theme must not wipe Full UI's name styling."""
    tab.set_layout_mode("full")
    tab.refresh_theme()  # explicit second pass — must not break Full styling

    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    # Full UI requires 28px font-size and no Compact-style clipping padding.
    assert "font-size: 28px" in sheet, f"Full name-label should be 28px; got {sheet!r}"
    assert "padding-right" not in sheet, (
        f"Full name-label should use the widened info column instead of padding; got {sheet!r}"
    )


def test_full_stats_labels_get_scaled_font(tab):
    """Stats labels (LAFF/beans) must get Full UI's 16px override, not
    compact's 13px, after refresh_theme + Full apply_theme."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    for label_list in (tab.laff_labels, tab.bean_labels):
        sheet = label_list[0].styleSheet()
        assert "font-size: 16px" in sheet, (
            f"Full stats label should be 16px; got {sheet!r}"
        )


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


def test_full_card_portrait_reference_size(qapp, tab):
    """Portrait uses Full's reference size when card height is at the reference."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)
    card.resize(632, 360)
    qapp.processEvents()

    wrap = card._portrait_wrap
    assert wrap.maximumWidth() == 168, (
        f"portrait wrap should be 168px wide; got {wrap.maximumWidth()}"
    )
    assert wrap.maximumHeight() == 168, (
        f"portrait wrap should be 168px tall; got {wrap.maximumHeight()}"
    )
    badge = tab.slot_badges[0]
    assert badge.maximumWidth() == 168 and badge.maximumHeight() == 168, (
        f"badge should be 168x168; got {badge.maximumSize()}"
    )


def test_full_status_indicator_is_not_clipped_by_portrait(qapp, tab):
    """The Full status dot may overlap past the portrait without being clipped."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)
    card.resize(632, 360)
    qapp.processEvents()

    indicator = card._status_indicator
    wrap = card._portrait_wrap
    assert indicator.parent() is card._active_root
    assert indicator.x() + indicator.width() > wrap.x() + wrap.width()


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


def test_game_pill_text_is_centered(tab):
    """TTR/CC pill labels should center text within the rounded pill."""
    from PySide6.QtCore import Qt

    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card._apply_game_pill_style()

    assert tab.game_badges[0].alignment() & Qt.AlignHCenter
    assert tab.game_badges[0].alignment() & Qt.AlignVCenter


def test_full_inactive_card_root_does_not_cover_card_frame(tab):
    """Inactive card content must not paint over the Full card frame/background."""
    tab.set_layout_mode("full")
    tab.refresh_theme()
    card = tab._full._cards[1]

    assert "transparent" in card._inactive_root.styleSheet()
    assert card._inactive_empty_area is not None
    assert "full_empty_area" in card._inactive_empty_area.styleSheet()
    assert tab._c()["bg_card"] in card._inactive_empty_area.styleSheet()


def test_full_layout_uses_full_surface_colors(tab):
    """Full Multitoon card surfaces are the light-mode source of truth."""
    tab.set_layout_mode("full")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab._full._cards[0].styleSheet()
    assert c["bg_card"] in card_sheet
    assert c["border_card"] in card_sheet


def test_compact_light_layout_uses_full_card_surface_colors(tab):
    """Compact light mode should match Full's card surface colors."""
    tab.settings_manager.set("theme", "light")
    tab.set_layout_mode("compact")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab.toon_cards[0].styleSheet()
    assert c["bg_card"] in card_sheet
    assert c["border_card"] in card_sheet
    assert c["bg_card_inner"] not in card_sheet
    assert c["border_muted"] not in card_sheet


def test_compact_dark_layout_keeps_original_card_surface_colors(tab):
    """Dark mode should keep Compact's existing card colors unchanged."""
    tab.settings_manager.set("theme", "dark")
    tab.set_layout_mode("compact")
    tab.refresh_theme()
    c = tab._c()

    card_sheet = tab.toon_cards[0].styleSheet()
    assert c["bg_card_inner"] in card_sheet
    assert c["border_muted"] in card_sheet
    assert c["bg_card"] not in card_sheet
    assert c["border_card"] not in card_sheet


def test_full_controls_scaled(tab):
    """Full UI controls use the captured reference design-surface sizes."""
    tab.set_layout_mode("full")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 43, (
        f"enable button should be 43px tall; got max height {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 118, (
        f"enable button should be 118px wide; got max width {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 43, (
        f"chat button should be 43px tall; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 43, (
        f"chat button should be 43px wide; got {chat.maximumWidth()}"
    )

    ka_bar = tab.ka_progress_bars[0]
    assert ka_bar.maximumHeight() == 9, (
        f"ka progress bar should be 9px tall; got {ka_bar.maximumHeight()}"
    )
    assert ka_bar.maximumWidth() == 150, (
        f"ka progress bar should use capped reference width; got {ka_bar.maximumWidth()}"
    )


def test_full_to_compact_roundtrip_restores_button_sizes(tab):
    """After Full → Compact, buttons must reset to Compact's creation defaults."""
    tab.set_layout_mode("full")
    assert tab.toon_buttons[0].maximumHeight() == 43

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


def test_full_to_compact_roundtrip_restores_icon_sizes(qapp, tab):
    """After Full at non-1.0 scale -> Compact, icon sizes must reset to defaults."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)
    card.resize(375, 214)
    qapp.processEvents()

    tab.set_layout_mode("compact")

    from PySide6.QtCore import QSize
    assert tab.chat_buttons[0].iconSize() == QSize(14, 14), (
        f"chat icon size should reset to 14x14; got {tab.chat_buttons[0].iconSize()}"
    )
    assert tab.keep_alive_buttons[0].iconSize() == QSize(14, 14), (
        f"KA icon size should reset to 14x14; got {tab.keep_alive_buttons[0].iconSize()}"
    )
    assert tab.laff_labels[0].iconSize() == QSize(16, 16), (
        f"laff icon size should reset to 16x16; got {tab.laff_labels[0].iconSize()}"
    )
    assert tab.bean_labels[0].iconSize() == QSize(16, 16), (
        f"bean icon size should reset to 16x16; got {tab.bean_labels[0].iconSize()}"
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


def test_full_grid_enforces_aspect_ratio(qapp, tab):
    """Cards in the Full UI grid must maintain a 7:4 aspect ratio."""
    tab.set_layout_mode("full")
    tab._full.resize(1200, 800)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() > 0 and card.height() > 0, "card must have real geometry"
    ratio = card.width() / card.height()
    assert abs(ratio - 1.75) < 0.1, (
        f"card aspect ratio should be ~1.75 (7:4); got {ratio:.2f}"
    )


def test_full_grid_caps_at_max_size(qapp, tab):
    """Cards must not exceed 1050x600 even on very large windows."""
    tab.set_layout_mode("full")
    tab._full.resize(3000, 2000)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() <= 1050, (
        f"card width should cap at 1050; got {card.width()}"
    )
    assert card.height() <= 600, (
        f"card height should cap at 600; got {card.height()}"
    )


def test_full_content_scales_with_card_size(qapp, tab):
    """Content must scale proportionally when the card shrinks."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)

    card.resize(632, 360)
    qapp.processEvents()
    portrait_full = tab.slot_badges[0].maximumHeight()
    assert portrait_full == 168, (
        f"portrait at scale 1.0 should be 168; got {portrait_full}"
    )

    card.resize(800, 450)
    qapp.processEvents()
    portrait_large = tab.slot_badges[0].maximumHeight()
    assert portrait_large > 168, (
        f"portrait should grow above reference size on taller cards; got {portrait_large}"
    )

    card.resize(375, 250)
    qapp.processEvents()
    portrait_small = tab.slot_badges[0].maximumHeight()
    assert portrait_small < 168, (
        f"portrait should shrink below 168 at smaller card size; got {portrait_small}"
    )
    assert portrait_small >= 92, (
        f"portrait should not go below min scale (0.55 * 168 ~= 92); got {portrait_small}"
    )


def test_full_progress_bar_width_is_capped(qapp, tab):
    """The Full controls row must not let the progress bar absorb all spare width."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)
    card.resize(800, 450)
    qapp.processEvents()

    bar = tab.ka_progress_bars[0]
    selector = tab.set_selectors[0]
    assert bar.maximumWidth() == bar.minimumWidth(), "bar should be fixed-width in Full"
    assert bar.maximumWidth() <= 190, (
        f"bar should cap at scaled reference width; got {bar.maximumWidth()}"
    )
    assert selector.maximumWidth() == selector.minimumWidth(), (
        "selector should be fixed-width in Full so right-side spacing remains intentional"
    )


def test_full_active_card_reference_ratios_hold_across_sizes(qapp, tab):
    """Active card internals should scale as one design surface, not drift by widget."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)

    def ratios(width, height):
        card.resize(width, height)
        qapp.processEvents()
        name_label, _ = tab.toon_labels[0]
        return {
            "portrait_w": tab.slot_badges[0].width() / card.width(),
            "portrait_x": card._portrait_wrap.x() / card.width(),
            "name_x": name_label.x() / card.width(),
            "button_y": tab.toon_buttons[0].y() / card.height(),
            "button_h": tab.toon_buttons[0].height() / card.height(),
            "progress_w": tab.ka_progress_bars[0].width() / card.width(),
            "selector_x": tab.set_selectors[0].x() / card.width(),
        }

    base = ratios(632, 360)
    large = ratios(1000, 570)
    for key, base_value in base.items():
        assert abs(base_value - large[key]) < 0.01, (
            f"{key} drifted: base={base_value:.4f}, large={large[key]:.4f}"
        )


def test_inactive_to_active_relayouts_against_current_card_size(qapp, tab):
    """Activating a card after it was resized while inactive must re-layout content.

    Regression for the maximize-then-start-service bug: _FullToonCard.resizeEvent
    is gated on _is_active, so resizes that arrive while the card is showing the
    inactive view leave _scale stale. When service later flips set_active(True),
    the active root showed with stale (small) positioning in a now-large card.
    """
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    # Card is inactive (no service running, no toon assigned).
    assert not card._is_active
    # Simulate the post-maximize cascade: card geometry grows to a real size while
    # still inactive. resizeEvent fires but _layout_active_content is gated out.
    card.resize(1000, 570)
    qapp.processEvents()

    # Now service starts and the card is activated. _scale must reflect 1000x570,
    # not the stale value from initial populate.
    card.set_active(True)
    qapp.processEvents()

    expected_scale = min(1000 / card._REF_CARD_W, 570 / card._REF_CARD_H)
    assert abs(card._scale - expected_scale) < 0.05, (
        f"scale should track card size after activation; expected ~{expected_scale:.2f}, got {card._scale:.2f}"
    )
    portrait_h = tab.slot_badges[0].height()
    assert portrait_h > 168, (
        f"portrait should grow above reference 168 in a 1000x570 card; got {portrait_h}"
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


def _setup_full_slot0(tab):
    """Common setup: full mode, slot 0 has a window, service running."""
    tab.set_layout_mode("full")
    tab.input_service = object()
    tab.window_manager.ttr_window_ids = ["fake-window-id"]
    tab.service_running = True


def test_full_status_indicator_red_when_disabled(qapp, tab):
    """Detected window + toon disabled + no keep-alive → red dot, no pulse."""
    _setup_full_slot0(tab)
    tab.enabled_toons[0] = False
    tab.keep_alive_enabled[0] = False
    tab.apply_visual_state(0)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card._status_state == "disabled", (
        f"expected status_state 'disabled'; got {card._status_state!r}"
    )
    assert card._status_indicator._dot_color_active.name() == "#e84141", (
        f"disabled dot should be red (#e84141); got {card._status_indicator._dot_color_active.name()}"
    )
    assert card._pulse_anim is None, "disabled state should not pulse"


def test_full_status_indicator_orange_pulse_when_keep_alive(qapp, tab):
    """Detected window + toon disabled + keep-alive on → orange dot, pulsing."""
    _setup_full_slot0(tab)
    tab.enabled_toons[0] = False
    tab.keep_alive_enabled[0] = True
    tab.apply_visual_state(0)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card._status_state == "keep_alive", (
        f"expected status_state 'keep_alive'; got {card._status_state!r}"
    )
    assert card._status_indicator._dot_color_active.name() == "#ff9900", (
        f"keep_alive dot should be orange (#ff9900); got {card._status_indicator._dot_color_active.name()}"
    )
    assert card._pulse_anim is not None, "keep_alive state should pulse"


def test_full_status_indicator_green_pulse_when_active(qapp, tab):
    """Detected window + toon enabled + service running → green dot, pulsing."""
    _setup_full_slot0(tab)
    tab.enabled_toons[0] = True
    tab.keep_alive_enabled[0] = False
    tab.apply_visual_state(0)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card._status_state == "active", (
        f"expected status_state 'active'; got {card._status_state!r}"
    )
    assert card._status_indicator._dot_color_active.name() == "#56c856", (
        f"active dot should be green (#56c856); got {card._status_indicator._dot_color_active.name()}"
    )
    assert card._pulse_anim is not None, "active state should pulse"
