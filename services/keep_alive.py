"""Keep-alive: the delay table and the per-cycle dispatch.

Shared by every runtime that owns a keep-alive loop. Nothing here keeps
state or touches a widget.
"""

from __future__ import annotations

from utils import logical_actions
from utils.game_registry import GameRegistry

KEEP_ALIVE_MASTER_KEY = "keep_alive_enabled"
KEEP_ALIVE_CONSENT_KEY = "keep_alive_consent_acknowledged"

# Label stored in the "keep_alive_delay" setting -> seconds between cycles.
KEEP_ALIVE_DELAYS = {
    "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10, "30 sec": 30,
    "1 min": 60, "3 min": 180, "5 min": 300, "10 min": 600,
}
KEEP_ALIVE_DELAY_FALLBACK = 60

KEEP_ALIVE_ACTION_LABELS = {"jump": "Jump", "book": "Book", "up": "Move Forward"}


def keep_alive_delay_seconds(settings_manager) -> float:
    """Seconds between normal keep-alive cycles for the current setting."""
    if not settings_manager:
        return KEEP_ALIVE_DELAY_FALLBACK
    label = settings_manager.get("keep_alive_delay", "30 sec")
    return KEEP_ALIVE_DELAYS.get(label, KEEP_ALIVE_DELAY_FALLBACK)


def dispatch_keep_alive_cycle(action, fire_toons, window_manager, keymap_manager,
                              input_service):
    """Dispatch one keep-alive cycle to the requested toon slots.

    Returns the number of toons that actually received a keypress (after
    per-toon game / binding resolution). A return of 0 with a non-empty
    fire_toons list means every candidate was skipped.

    The key sent is ALWAYS the game client's own binding, mirroring the
    router's outbound rule (_send_logical_action_km): CC movement uses the
    WASD-lock canonical, everything else uses set 0 (the config-driven
    Default that tracks the client's settings file). A toon's assigned SET
    must never leak here - sets are an input-translation layer for what the
    USER presses, not what the client understands. Resolving through the
    set sent raw Alt_R (an Arrows-set jump rebind) to a TTR client whose
    real jump is space, which the client read as its side-agnostic 'alt'
    stickerBook binding: the book toggled open every keep-alive cycle.
    """
    from utils import cc_isolation

    logical = "forward" if action == "up" else action
    cc_canonical = cc_isolation.canonical_to_ttmt_keysyms(
        cc_isolation.DEFAULT_CANONICAL
    )
    window_ids = window_manager.get_window_ids()
    # Chat gate: keep-alive must never type its key into an open chat box
    # (the focused toon's during a capture, or a bg box TTMT mirrored open).
    # Fail-open via getattr so bare test stubs without the method keep the
    # historical behavior.
    chat_skip = getattr(input_service, "keep_alive_skip_window", None)
    fired = 0
    for i in fire_toons:
        if i >= len(window_ids):
            continue
        wid = window_ids[i]
        if chat_skip is not None:
            try:
                if chat_skip(wid):
                    continue
            except Exception:
                pass
        try:
            game = GameRegistry.instance().get_game_for_window(str(wid))
        except Exception:
            game = None
        if game not in ("ttr", "cc"):
            continue
        if not logical_actions.supports(game, logical):
            continue
        key = cc_canonical.get(logical) if game == "cc" else None
        if not key:
            key = keymap_manager.get_key_for_action(game, 0, logical)
        if not key:
            continue
        input_service.send_keep_alive_to_window(wid, key)
        fired += 1
    return fired
