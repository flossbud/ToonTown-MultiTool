"""Keyset rules shared by the Settings Keysets page and the launchpad
Keysets sheet: when keyset 1 is locked to the game's own key settings, and
the in-set conflict message. Moved here from keysets_page.py and
split_editor.py so the sheet does not depend on the old page."""
from __future__ import annotations

import os


CONFLICT_TEXT = ("Some keys are assigned to more than one action - "
                 "highlighted in red.")


def default_set_locked(game: str, settings_manager=None) -> bool:
    """True when a game config file is present and drives this game's
    Default set, so its key fields must not be hand-editable.

    TTR: settings.json is located (the startup auto-detect re-applies it
    every launch, so hand edits are clobbered anyway), OR the cached
    last-detected keymap exists (the startup fallback re-applies THAT
    when settings.json is momentarily unreadable - edits made in such a
    window would be silently lost, so the lock holds).
    CC: any discovered install resolves a preferences.json.
    No config source at all -> editable."""
    if game == "ttr":
        try:
            from utils.ttr_settings import locate_settings_file
            from services.ttr_login_service import find_engine_path
        except Exception:
            return False
        engine = ""
        if settings_manager is not None:
            engine = settings_manager.get("ttr_engine_dir", "") or ""
        if not engine or not os.path.exists(engine):
            try:
                engine = find_engine_path() or ""
            except Exception:
                engine = ""
        try:
            if locate_settings_file(engine_dir=engine or None):
                return True
        except Exception:
            pass
        if settings_manager is not None:
            cached = settings_manager.get("last_detected_keymap", None)
            if isinstance(cached, dict) and cached:
                return True
        return False
    try:
        from utils.cc_settings import locate_cc_preferences
        from services.wine_runtimes import discover_cc_installs
    except Exception:
        return False
    try:
        installs = discover_cc_installs() or []
    except Exception:
        return False
    for install in installs:
        try:
            if locate_cc_preferences(install):
                return True
        except Exception:
            continue
    return False
