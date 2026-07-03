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


def _both_keysets() -> tuple[str, ...]:
    """All movement keys across both presets — the route_all fallback set
    when the caller supplies no route_keys."""
    return ("w", "a", "s", "d", "Up", "Down", "Left", "Right")


# keysym name -> the virtual-key code the WH_KEYBOARD_LL hook reports for
# that physical key. NOTE the modifiers use the LEFT/RIGHT-DISTINCT codes
# (VK_LSHIFT 0xA0 .. VK_RMENU 0xA5): low-level hooks always deliver the
# side-specific vk, never the generic VK_SHIFT/VK_CONTROL/VK_MENU that
# window messages carry. This table is therefore the HOOK-side inverse and
# must not be conflated with win32_backend.WIN32_MODIFIER_OVERRIDES, which
# is the OUTBOUND (PostMessage wparam) table and deliberately generic.
_HOOK_VK_FOR_KEYSYM: dict[str, int] = {
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "space": 0x20, "Tab": 0x09, "Return": 0x0D, "Escape": 0x1B,
    "BackSpace": 0x08, "Delete": 0x2E, "Insert": 0x2D,
    "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22,
    "Shift_L": 0xA0, "Shift_R": 0xA1,
    "Control_L": 0xA2, "Control_R": 0xA3,
    "Alt_L": 0xA4, "Alt_R": 0xA5,
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
    **{f"KP_{i}": 0x60 + i for i in range(10)},
    "KP_Multiply": 0x6A, "KP_Add": 0x6B, "KP_Subtract": 0x6D,
    "KP_Decimal": 0x6E, "KP_Divide": 0x6F,
    **{c: ord(c) - 32 for c in "abcdefghijklmnopqrstuvwxyz"},
    **{c: ord(c) for c in "0123456789"},
}


def _hook_vk_for_keysym(keysym: str) -> Optional[int]:
    """Resolve a keymap keysym to its LL-hook vk. Named keys and
    letters/digits come from the static table; other single printable chars
    (e.g. '\\' for TTR's performAction) resolve through VkKeyScan, which is
    layout-aware and only exists on Windows."""
    vk = _HOOK_VK_FOR_KEYSYM.get(keysym)
    if vk is not None:
        return vk
    if len(keysym) == 1 and sys.platform == "win32":
        try:
            import win32api
            vk = win32api.VkKeyScan(keysym) & 0xFF
            if vk not in (0, 0xFF):
                return vk
        except Exception:
            return None
    return None


def win32_grabber_available() -> bool:
    """Whether the Windows grabber can run on this platform."""
    return sys.platform == "win32"


class Win32MovementKeyGrabber:
    # X11's active grab redirects ALL keyboard events to the grabbing client, so
    # non-movement keys must be re-sent to the focused window ("focused
    # passthrough"). The Windows WH_KEYBOARD_LL hook is NON-exclusive: only keys
    # we explicitly suppress are blocked, so non-movement keys reach the focused
    # window natively and re-sending them would double them. Hence: False.
    needs_focused_passthrough = False

    def __init__(self) -> None:
        self._grabbed_keysyms: Optional[frozenset[str]] = None
        self._vk_to_keysym: dict[int, str] = {}
        self._should_consume: Optional[Callable[[str], bool]] = None
        self._on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None

    def prepare(
        self,
        should_consume: Callable[[str], bool],
        on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> bool:
        if not win32_grabber_available():
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
        """route_all=True (TTR strict): suppress every key in route_keys — the
        union of all keys bound in any of the foreground game's sets, supplied
        by InputService from the keymap — so a bound key NEVER reaches the
        focused window natively and the router re-synthesizes the client's own
        binding instead. This is what lets a rebound non-movement key (e.g.
        jump=Alt_R) drive the focused toon, and what stops the raw modifier
        from triggering the client's native side-agnostic binding (alt=book).
        The suppress set must stay a subset of the router's movement-class
        classification (same keymap union) or a suppressed key would be
        silently eaten: on Windows there is no focused-passthrough re-send.
        Without route_keys, route_all falls back to the 8 preset movement
        keys (pre-keymap behavior). route_all=False (CC, default): suppress
        only the opposite keyset. passthrough_keysyms is accepted for parity
        but ignored (the non-exclusive hook needs no passthrough list). Fires
        on_grabs_changed(canonical_set) synchronously after updating the grab
        set, or on_grabs_changed(None) if the resulting grab set is empty."""
        if route_all:
            keys = tuple(route_keys) if route_keys else _both_keysets()
        else:
            keys = _opposite_keys(canonical_set)
        self._grabbed_keysyms = frozenset(keys) if keys else None
        vk_map: dict[int, str] = {}
        for keysym in self._grabbed_keysyms or ():
            vk = _hook_vk_for_keysym(keysym)
            if vk is not None:
                vk_map[vk] = keysym
        self._vk_to_keysym = vk_map
        # Report the focused canonical only when a real grab set is installed, so
        # InputService._on_grabs_changed never marks strict active without
        # suppression actually happening.
        self._notify_grabs_changed(canonical_set if self._grabbed_keysyms else None)

    def uninstall_grabs(self) -> None:
        self._grabbed_keysyms = None
        self._vk_to_keysym = {}
        self._notify_grabs_changed(None)

    def keysym_for_vk(self, vk) -> Optional[str]:
        """Hook-side vk -> keysym for the CURRENT grab set, or None when the
        vk is not a grabbed key (the event filter then falls back to its
        static movement table / normal processing)."""
        if vk is None:
            return None
        return self._vk_to_keysym.get(vk)

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
            print(f"[win32_movement_grabber] on_grabs_changed raised: {e}")

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
        self._on_grabs_changed = None
