"""Windows suppression-decision authority for the pynput hook.

Why: Corporate Clash's engine accepts both WASD and arrow keys for
movement and ignores attempts to remove arrows from preferences.json
(see utils/cc_isolation.py). On Linux, utils/x11_movement_grabber.py
installs a passive XGrabKey so the conflicting keyset never reaches
the focused window. On Windows there is no XGrabKey, but pynput's
WH_KEYBOARD_LL hook can suppress events by returning False from its
callback. This module owns the state machine that decides which keys
should be suppressed; HotkeyManager queries should_suppress() and
returns False from its pynput callback accordingly.

The lifecycle API (prepare / install_grabs / uninstall_grabs / stop)
mirrors MovementKeyGrabber so InputService can install/uninstall on
focus changes identically on both platforms. The passthrough_keysyms
parameter on install_grabs is accepted for parity but ignored: the
Windows hook is non-exclusive, so non-grabbed keys reach the focused
window naturally.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional


def _opposite_keys(canonical_set: str) -> tuple[str, ...]:
    if canonical_set == "wasd":
        return ("Up", "Down", "Left", "Right")
    if canonical_set == "arrows":
        return ("w", "a", "s", "d")
    return ()


def win32_grabber_available() -> bool:
    """Whether the Windows grabber can run on this platform."""
    return sys.platform == "win32"


class Win32MovementKeyGrabber:
    def __init__(self) -> None:
        self._grabbed_keysyms: Optional[frozenset[str]] = None
        self._should_consume: Optional[Callable[[str], bool]] = None

    def prepare(self, should_consume: Callable[[str], bool]) -> bool:
        if not win32_grabber_available():
            return False
        self._should_consume = should_consume
        return True

    def install_grabs(
        self,
        canonical_set: str,
        passthrough_keysyms: Optional[list[str]] = None,
    ) -> None:
        keys = _opposite_keys(canonical_set)
        self._grabbed_keysyms = frozenset(keys) if keys else None

    def uninstall_grabs(self) -> None:
        self._grabbed_keysyms = None

    def should_suppress(self, keysym: str) -> bool:
        if self._grabbed_keysyms is None:
            return False
        if keysym not in self._grabbed_keysyms:
            return False
        consume = self._should_consume
        if consume is None:
            return False
        try:
            return bool(consume(keysym))
        except Exception:
            return False

    def stop(self) -> None:
        self.uninstall_grabs()
        self._should_consume = None
