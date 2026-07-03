"""Map hotkey action ids to app behavior. Pure wiring: every target is
injected, every handler no-ops cleanly when inapplicable (framed mode,
unassigned slot), and unknown ids simply aren't in the map - the caller
(main._on_hotkey_action) drops them with a trace."""
from __future__ import annotations

from utils.settings_keys import CLICK_SYNC_ENABLED, HOTKEY_LAUNCH_SLOTS


def build_dispatch(*, mode_controller, launch_tab, multitoon_tab,
                   settings_manager, load_profile):
    def _overlay(method, *args, **kwargs):
        if not getattr(mode_controller, "is_active", False):
            return
        fn = getattr(mode_controller, method, None)
        if fn is not None:
            fn(*args, **kwargs)

    def _launch_slot(slot: str):
        slots = settings_manager.get(HOTKEY_LAUNCH_SLOTS, {}) or {}
        if not isinstance(slots, dict):
            slots = {}
        account_id = slots.get(slot)
        if not account_id:
            return
        game = launch_tab.game_of_account(account_id)
        if game is None:
            return
        launch_tab.launch_account(game, account_id)

    def _flip_click_sync():
        current = bool(settings_manager.get(CLICK_SYNC_ENABLED, False))
        settings_manager.set(CLICK_SYNC_ENABLED, not current)

    dispatch = {
        "overlay.toggle_cards":
            lambda: _overlay("toggle_cards_hidden", animate=True),
        "overlay.scale_up": lambda: _overlay("set_scale_by_notches", 1),
        "overlay.scale_down": lambda: _overlay("set_scale_by_notches", -1),
        "service.toggle": multitoon_tab.toggle_service,
        "keepalive.toggle_all": multitoon_tab.toggle_keep_alive_all,
        "clicksync.toggle": _flip_click_sync,
        "app.refresh": multitoon_tab._on_refresh_requested,
    }
    for n in (1, 2, 3, 4):
        dispatch[f"launch.slot_{n}"] = (
            lambda slot=str(n): _launch_slot(slot))
    for n in (1, 2, 3, 4, 5):
        dispatch[f"profile.load_{n}"] = (
            lambda idx=n - 1: load_profile(idx))
    return dispatch
