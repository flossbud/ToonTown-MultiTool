"""Centralized settings key definitions for type-safe access."""

THEME = "theme"
SHOW_DEBUG_TAB = "show_debug_tab"
KEEP_ALIVE_ACTION = "keep_alive_action"
KEEP_ALIVE_DELAY = "keep_alive_delay"
ACTIVE_PROFILE = "active_profile"
INPUT_BACKEND = "input_backend"
STRICT_TTR_SEPARATION = "strict_ttr_separation"
TTR_ENGINE_DIR = "ttr_engine_dir"
CC_ENGINE_DIR = "cc_engine_dir"
CC_ENGINE_INSTALL_SIGNATURE = "cc_engine_install_signature"
CC_ENGINE_INSTALL_SET_HASH = "cc_engine_install_set_hash"
CC_HIDE_LAUNCH_CONSOLE = "cc_hide_launch_console"
CC_EXTERNAL_LOG_DIR = "cc_external_log_dir"
LAUNCH_QUIT_CONFIRM_DISMISSED = "launch_quit_confirm_dismissed"
SHOW_HINTS = "show_hints"
REDUCE_MOTION = "reduce_motion"
REDUCE_MOTION_SET_EXPLICITLY = "reduce_motion_set_explicitly"
ADVANCED_COLLAPSED = "advanced_collapsed"

# Update flow (added 2026-05-16)
CHECK_FOR_UPDATES_AT_STARTUP = "check_for_updates_at_startup"
UPDATE_SKIPPED_VERSION = "update_skipped_version"
UPDATE_LAST_CHECK_AT = "update_last_check_at"
UPDATE_LAST_CHECK_RESULT = "update_last_check_result"

# Launch tab section collapse (added 2026-05-23)
LAUNCH_SECTION_TTR_COLLAPSED = "launch_section_ttr_collapsed"
LAUNCH_SECTION_CC_COLLAPSED  = "launch_section_cc_collapsed"

# Settings tab navigation (added 2026-05-23)
SETTINGS_ACTIVE_CATEGORY = "settings_active_category"

# Chat handling mode (added 2026-05-26; extended 2026-06-09)
CHAT_HANDLING_MODE = "chat_handling_mode"

# Canonical mode values (2026-06-09: replaces the simple/advanced switch)
CHAT_HANDLING_FOCUSED_ONLY = "focused_only"
CHAT_HANDLING_ALL_TOONS = "all_toons"
CHAT_HANDLING_KEYSET_DYNAMIC = "keyset_dynamic"
CHAT_HANDLING_PER_TOON = "per_toon"

CHAT_HANDLING_MODE_VALUES = (
    CHAT_HANDLING_FOCUSED_ONLY,
    CHAT_HANDLING_ALL_TOONS,
    CHAT_HANDLING_KEYSET_DYNAMIC,
    CHAT_HANDLING_PER_TOON,
)

CHAT_HANDLING_MODE_DEFAULT = CHAT_HANDLING_FOCUSED_ONLY

# Legacy values from the original Simple/Advanced switch, mapped to canonical
# modes at read time. No write migration: the canonical value persists only
# when the user next touches the Chat Handling selector.
#
# Legacy "simple" is intentionally NOT mapped: it was the old implicit
# default, not an explicit mode selection, so it falls through
# to CHAT_HANDLING_MODE_DEFAULT below. Only "advanced" (an explicit opt-in
# to the per-card chat buttons) is preserved.
_LEGACY_CHAT_HANDLING = {
    "advanced": CHAT_HANDLING_PER_TOON,
}


def normalize_chat_handling_mode(raw) -> str:
    """Map any stored/legacy/None chat-handling value to a canonical mode.

    - the four canonical values pass through unchanged
    - legacy 'advanced' -> 'per_toon'
    - anything else (including legacy 'simple', None, unknown strings, or a
      non-string such as a corrupt list/dict from a malformed settings
      file) -> default
    """
    if isinstance(raw, str):
        if raw in CHAT_HANDLING_MODE_VALUES:
            return raw
        if raw in _LEGACY_CHAT_HANDLING:
            return _LEGACY_CHAT_HANDLING[raw]
    return CHAT_HANDLING_MODE_DEFAULT

# Windows UIPI elevation prompt (added 2026-06-05)
UIPI_ELEVATION_PROMPT_DISMISSED = "uipi_elevation_prompt_dismissed"

# Windows administrator notice banner (added 2026-06-05)
WINDOWS_ADMIN_NOTICE_DISMISSED = "windows_admin_notice_dismissed"

# Click sync (added 2026-06-10): mirror left-button gestures between
# same-aspect TTR windows. Default OFF (opt-in posture).
CLICK_SYNC_ENABLED = "click_sync_enabled"

# Ghost cursors (added 2026-06-11): per-toon glove overlays on windows
# receiving synthetic click-sync input. Pure display (no input fired),
# so default ON; no consent gate needed.
GHOST_CURSORS_ENABLED = "click_sync_ghost_cursors"

# Ghost cursors can press card controls (added 2026-06-20): in transparent
# overlay mode, a ghost cursor over a card control fires it like the real
# cursor. Driven by a live user click on the app's own UI, so default ON; gated
# at runtime on GHOST_CURSORS_ENABLED too.
GHOST_CURSORS_CONTROL_CARDS = "click_sync_ghost_control_cards"

# Start in Float UI mode (added 2026-06-24): open directly into the transparent
# overlay at launch instead of the windowed UI. Default OFF (explicit opt-in).
# Read at startup by main.py; written by the General -> Appearance toggle.
START_IN_FLOAT_UI_MODE = "start_in_float_ui_mode"

# Float UI startup crash-loop breaker (added 2026-06-24): set just before the
# startup auto-enter and cleared right after it returns. If a launch finds it
# already set, the previous auto-enter crashed/hung mid-enter, so Float UI is
# skipped that launch (fall back to the windowed UI + a one-time notice).
FLOAT_UI_STARTUP_PENDING = "float_ui_startup_pending"
