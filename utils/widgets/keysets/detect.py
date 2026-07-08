"""Detect-apply: read the live game config and write it onto the Default set.

Ported verbatim (minus the old tab's per-game card rebuild / theme refresh,
which the SplitEditor now owns) out of tabs/keymap_tab.py's
`_on_detect_ttr_settings` / `_on_detect_cc_settings`. These functions locate
the game's on-disk settings, parse them, and apply the controls to movement
set 0 through `keymap_manager`. They return the number of updates applied so
the caller can decide whether to re-render.

Kept in the keysets package because keymap_tab.py is being deleted.
"""

from __future__ import annotations

import os


def detect_settings_for_game(game: str, keymap_manager, settings_manager) -> int:
    """Dispatch to the per-game detect routine. Returns the number of updates
    applied to the Default set (0 when nothing was found/parsed)."""
    if game == "ttr":
        return detect_ttr_settings(keymap_manager, settings_manager)
    return detect_cc_settings(keymap_manager, settings_manager)


def detect_ttr_settings(keymap_manager, settings_manager) -> int:
    from utils.ttr_settings import (
        locate_settings_file, parse_ttr_settings, apply_ttr_controls_to_set,
    )
    from services.ttr_login_service import find_engine_path

    engine_path = None
    if settings_manager:
        engine_path = settings_manager.get("ttr_engine_dir", "")
    if not engine_path or not os.path.exists(engine_path):
        engine_path = find_engine_path()

    path = locate_settings_file(engine_dir=engine_path)
    if not path:
        print("[Keysets] Could not find TTR settings.json")
        return 0

    try:
        settings = parse_ttr_settings(path)
    except Exception as e:
        print(f"[Keysets] Failed to parse TTR settings.json: {e}")
        return 0

    updates = apply_ttr_controls_to_set(keymap_manager, 0, settings.controls)
    if updates > 0:
        print(f"[Keysets] Detected {updates} TTR settings from {path}")
    return updates


def detect_cc_settings(keymap_manager, settings_manager) -> int:
    from utils.cc_settings import (
        locate_cc_preferences, parse_cc_preferences, apply_cc_controls_to_set,
    )
    try:
        from services.wine_runtimes import discover_cc_installs
    except Exception:
        discover_cc_installs = None

    install = None
    installs = []
    if discover_cc_installs is not None:
        try:
            installs = discover_cc_installs() or []
        except Exception as e:
            print(f"[Keysets] CC install discovery failed: {e}")

    # Prefer the install currently active in Settings if it's discoverable.
    cc_dir = settings_manager.get("cc_engine_dir", "") if settings_manager else ""
    if cc_dir:
        for cand in installs:
            exe = getattr(cand, "exe_path", None)
            if exe and os.path.dirname(exe) == cc_dir:
                install = cand
                break
    if install is None and installs:
        install = installs[0]
    if install is None:
        print("[Keysets] No CC install detected")
        return 0

    path = locate_cc_preferences(install)
    if not path:
        print("[Keysets] Could not find CC preferences.json")
        return 0

    try:
        settings = parse_cc_preferences(path)
    except Exception as e:
        print(f"[Keysets] Failed to parse CC preferences.json: {e}")
        return 0

    updates = apply_cc_controls_to_set(keymap_manager, 0, settings)
    if updates > 0:
        print(f"[Keysets] Detected {updates} CC settings from {path}")
    return updates
