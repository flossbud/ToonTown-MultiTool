"""macOS suppression-decision authority for the pynput Darwin listener.

Why: Corporate Clash's engine accepts both WASD and arrow keys for
movement and ignores attempts to remove arrows from preferences.json
(see utils/cc_isolation.py). On Linux, utils/x11_movement_grabber.py
installs a passive XGrabKey so the conflicting keyset never reaches
the focused window. On macOS there is no XGrabKey, but pynput's
darwin_intercept filter can suppress events by returning None from its
callback. This module owns the state machine that decides which keys
should be suppressed; HotkeyManager queries should_suppress() and
returns None from its darwin_intercept callback accordingly.

The lifecycle API (prepare / install_grabs / uninstall_grabs / stop)
mirrors MovementKeyGrabber so InputService can install/uninstall on
focus changes identically on all platforms. The passthrough_keysyms
parameter on install_grabs is accepted for parity but ignored: the
darwin_intercept filter is non-exclusive, so non-grabbed keys reach
the focused window naturally.
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


def _both_keysets() -> tuple[str, ...]:
    """All movement keys across both presets — the route_all grab set."""
    return ("w", "a", "s", "d", "Up", "Down", "Left", "Right")


def macos_grabber_available() -> bool:
    """Whether the macOS grabber can run on this platform."""
    return sys.platform == "darwin"


class MacOSMovementKeyGrabber:
    # X11's active grab redirects ALL keyboard events to the grabbing client, so
    # non-movement keys must be re-sent to the focused window ("focused
    # passthrough"). The macOS darwin_intercept filter is NON-exclusive: only keys
    # we explicitly suppress are blocked, so non-movement keys reach the focused
    # window natively and re-sending them would double them. Hence: False.
    needs_focused_passthrough = False

    def __init__(self) -> None:
        self._grabbed_keysyms: Optional[frozenset[str]] = None
        self._should_consume: Optional[Callable[[str], bool]] = None
        self._on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None

    def prepare(
        self,
        should_consume: Callable[[str], bool],
        on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> bool:
        if not macos_grabber_available():
            return False
        self._should_consume = should_consume
        self._on_grabs_changed = on_grabs_changed
        return True

    def install_grabs(
        self,
        canonical_set: str,
        passthrough_keysyms: Optional[list[str]] = None,
        route_all: bool = False,
        route_keys=None,
    ) -> None:
        """route_all=True (TTR strict): grab BOTH keysets so every focused-window
        movement key is suppressed and the router re-synthesizes the correct
        native key. route_all=False (CC, default): suppress only the opposite
        keyset. passthrough_keysyms is accepted for parity but ignored (the
        non-exclusive darwin_intercept filter needs no passthrough list). Fires
        on_grabs_changed(canonical_set) synchronously after updating the grab
        set, or on_grabs_changed(None) if the resulting grab set is empty.

        route_keys is accepted for signature parity with the Win32 grabber
        and ignored for now: darwin still suppresses only the preset movement
        keysets; honoring the full keymap union here is a recorded
        follow-up."""
        keys = _both_keysets() if route_all else _opposite_keys(canonical_set)
        self._grabbed_keysyms = frozenset(keys) if keys else None
        # Report the focused canonical only when a real grab set is installed, so
        # InputService._on_grabs_changed never marks strict active without
        # suppression actually happening.
        self._notify_grabs_changed(canonical_set if self._grabbed_keysyms else None)

    def uninstall_grabs(self) -> None:
        self._grabbed_keysyms = None
        self._notify_grabs_changed(None)

    def _notify_grabs_changed(self, canonical: Optional[str]) -> None:
        cb = self._on_grabs_changed
        if cb is None:
            return
        try:
            cb(canonical)
        except Exception as e:  # noqa: BLE001
            # A callback error must never unwind the focus-change / settings-
            # change path that drives install/uninstall (mirrors the X11 grabber,
            # which shields its on_grabs_changed call too). Log for diagnostics
            # rather than swallowing silently.
            print(f"[macos_movement_grabber] on_grabs_changed raised: {e}")

    def should_suppress(self, keysym: str) -> bool:
        # Snapshot the grab set once. should_suppress runs on the pynput tap
        # thread while install_grabs/uninstall_grabs run on the focus-change
        # thread, which can reassign _grabbed_keysyms to None between two reads.
        # Reading the field twice would risk `keysym not in None` -> TypeError on
        # that race; a single local read closes it (the set is an immutable
        # frozenset that is only ever replaced, never mutated). This is a
        # deliberate hardening over the win32 sibling, which reads it twice.
        grabbed = self._grabbed_keysyms
        if grabbed is None:
            return False
        if keysym not in grabbed:
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
        self._on_grabs_changed = None
