"""A chord the hotkey hook resolves to an action must be SKIPPED (never enter
the InputService key queue, press or release), must fire the on_hotkey callback
when one is provided (the win/darwin fallback path; Linux passes None and lets
the X11 provider fire), must only be consulted while input capture is allowed,
and must not strand a skipped key's release after the listener stops mid-hold.
Modifier families (ctrl/alt/shift/super) are tracked side-agnostically so the
hook sees the chord's modifier set."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

from services.hotkey_manager import HotkeyManager


def _hook(mods, key):
    """Test bindings: F5 -> app.refresh (no modifiers)."""
    if key == "F5" and not mods:
        return "app.refresh"
    return None


def _make_hotkey_manager(capture: bool = True, hook=_hook, on_hotkey=None):
    wm = MagicMock()
    wm.should_capture_input.return_value = capture
    q = queue.Queue(maxsize=10)
    hm = HotkeyManager(wm, q, hotkey_hook=hook, on_hotkey=on_hotkey)
    return hm, q


def _fake_key(char: str = None, name: str = None, vk: int = None):
    k = MagicMock()
    k.char = char
    k.name = name
    k.vk = vk
    return k


def _f5():
    # pynput exposes F5 as a named key 'f5'; normalize_key -> 'F5'.
    return _fake_key(name="f5")


def test_bound_chord_is_skipped_and_fires_callback():
    fired = []
    hm, q = _make_hotkey_manager(on_hotkey=fired.append)
    assert hm.on_global_key_press(_f5()) is None
    assert fired == ["app.refresh"]
    assert q.qsize() == 0   # bound chord: never routed to the input queue


def test_bound_chord_skip_without_fire():
    # Linux mode: on_hotkey is None (the X11 provider fires the action); the
    # pynput hook still SKIPS the chord so it never reaches the input queue.
    hm, q = _make_hotkey_manager(on_hotkey=None)
    assert hm.on_global_key_press(_f5()) is None
    assert q.qsize() == 0


def test_release_of_skipped_key_is_also_skipped():
    fired = []
    hm, q = _make_hotkey_manager(on_hotkey=fired.append)
    hm.on_global_key_press(_f5())
    assert hm.on_global_key_release(_f5()) is None
    assert q.qsize() == 0   # neither the press nor the release is enqueued
    assert fired == ["app.refresh"]


def test_modifier_families_tracked():
    calls = []

    def hook(mods, key):
        calls.append((mods, key))
        return None

    hm, _ = _make_hotkey_manager(hook=hook)
    hm.on_global_key_press(_fake_key(name="alt_l"))   # pynput Key.alt_l
    hm.on_global_key_press(_fake_key(char="h"))
    assert (frozenset({"alt"}), "h") in calls
    hm.on_global_key_release(_fake_key(name="alt_l"))
    hm.on_global_key_press(_fake_key(char="h"))
    assert (frozenset(), "h") in calls                # alt released -> no mods


def test_hook_not_consulted_when_capture_disabled():
    calls = []

    def hook(mods, key):
        calls.append((mods, key))
        return "app.refresh"

    fired = []
    hm, q = _make_hotkey_manager(capture=False, hook=hook, on_hotkey=fired.append)
    assert hm.on_global_key_press(_f5()) is None
    assert calls == [] and fired == []
    assert q.qsize() == 0


def test_stop_listener_clears_hotkey_down():
    # A focus-out can stop the listener while a bound chord's key is still
    # physically held; _hotkey_down must not wedge across the stop.
    hm, _ = _make_hotkey_manager(on_hotkey=lambda _aid: None)
    hm.on_global_key_press(_f5())
    assert "F5" in hm._hotkey_down
    hm.is_listening = True
    hm.listener = MagicMock()
    hm._stop_listener()
    assert hm._hotkey_down == set()
