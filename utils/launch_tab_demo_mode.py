"""Demo-mode fixtures for the Launch tab. Gated by TTMT_DEMO_LAUNCH_TAB.

Values:
  "populated" - both sections filled with one fake account per state so
                a single screenshot captures every state simultaneously.
  "empty"     - both sections empty so the empty-state can be screenshotted.
  (unset)     - no demo data; production behavior.

The LaunchTab consults `get_demo_fixtures()` on init and, when not None,
uses these dicts instead of the real credentials manager and forces tiles
into the specified states (bypassing login workers entirely)."""
from __future__ import annotations

import os
from typing import Any


_POPULATED = {
    "ttr": [
        {"label": "PinkPirate", "username": "pink@example", "state": "idle"},
        {"label": "FlashHotrod", "username": "flash@example", "state": "running"},
        {"label": "DizzyMcSwirl", "username": "dizzy@example", "state": "logging_in",
         "message": "Reaching server..."},
        {"label": "CaptainCrash", "username": "crash@example", "state": "failed",
         "message": "Bad credentials",
         "raw": "TTR API HTTP 401:\n{'success': 'false', 'banner': 'Incorrect username or "
                "password. Please check your credentials and try again.'}"},
    ],
    "cc": [
        {"label": "SaltyMcKraken", "username": "salty@example", "state": "need_2fa"},
        {"label": "BoomerSplash", "username": "boomer@example", "state": "queued",
         "message": "pos 12"},
        {"label": "SplashyJim", "username": "splashy@example", "state": "launching"},
    ],
}


def get_demo_fixtures() -> dict[str, list[dict[str, Any]]] | None:
    """Return demo data dict or None if not in demo mode."""
    mode = os.environ.get("TTMT_DEMO_LAUNCH_TAB", "").lower()
    if not mode:
        return None
    if mode == "populated":
        return _POPULATED
    if mode == "empty":
        return {"ttr": [], "cc": []}
    return None


def is_demo_mode() -> bool:
    return get_demo_fixtures() is not None
