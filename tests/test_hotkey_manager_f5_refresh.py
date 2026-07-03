"""A chord the hotkey hook resolves to an action must be SKIPPED (never enter
the InputService key queue, press or release), must emit hotkey_triggered when
fire_hotkeys is set (the win/darwin path; the emission happens on the pynput
listener thread and Qt auto-queues it to the GUI-thread receiver -- Linux
passes False and lets the X11 provider fire), must only be consulted while
input capture is allowed, and must not strand a skipped key's release after
the listener stops mid-hold. Modifier families (ctrl/alt/shift/super) are
tracked side-agnostically so the hook sees the chord's modifier set."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

from services.hotkey_manager import HotkeyManager


def _hook(mods, keys):
    """Test bindings: F5 -> app.refresh (no modifiers). The hook is a pure
    (mods, keys-frozenset) lookup; the manager consults it with the full
    held set first, then the just-pressed key alone."""
    if keys == frozenset({"F5"}) and not mods:
        return "app.refresh"
    return None


def _make_hotkey_manager(capture: bool = True, hook=_hook,
                         fire_hotkeys: bool = False, repeat_ok=frozenset()):
    wm = MagicMock()
    wm.should_capture_input.return_value = capture
    q = queue.Queue(maxsize=10)
    hm = HotkeyManager(wm, q, hotkey_hook=hook, fire_hotkeys=fire_hotkeys,
                       hotkey_repeat_ok=repeat_ok)
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


def test_bound_chord_is_skipped_and_fires_signal():
    fired = []
    hm, q = _make_hotkey_manager(fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    assert hm.on_global_key_press(_f5()) is None
    assert fired == ["app.refresh"]
    assert q.qsize() == 0   # bound chord: never routed to the input queue


def test_bound_chord_skip_without_fire():
    # Linux mode: fire_hotkeys=False (the X11 provider fires the action); the
    # pynput hook still SKIPS the chord so it never reaches the input queue.
    fired = []
    hm, q = _make_hotkey_manager(fire_hotkeys=False)
    hm.hotkey_triggered.connect(fired.append)
    assert hm.on_global_key_press(_f5()) is None
    assert fired == []
    assert q.qsize() == 0


def test_release_of_skipped_key_is_also_skipped():
    fired = []
    hm, q = _make_hotkey_manager(fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_f5())
    assert hm.on_global_key_release(_f5()) is None
    assert q.qsize() == 0   # neither the press nor the release is enqueued
    assert fired == ["app.refresh"]


def test_modifier_families_tracked():
    calls = []

    def hook(mods, keys):
        calls.append((mods, keys))
        return None

    hm, _ = _make_hotkey_manager(hook=hook)
    hm.on_global_key_press(_fake_key(name="alt_l"))   # pynput Key.alt_l
    hm.on_global_key_press(_fake_key(char="h"))
    assert (frozenset({"alt"}), frozenset({"h"})) in calls
    hm.on_global_key_release(_fake_key(name="alt_l"))
    hm.on_global_key_release(_fake_key(char="h"))
    hm.on_global_key_press(_fake_key(char="h"))
    assert (frozenset(), frozenset({"h"})) in calls   # alt released -> no mods


def test_hook_not_consulted_when_capture_disabled():
    calls = []

    def hook(mods, keys):
        calls.append((mods, keys))
        return "app.refresh"

    fired = []
    hm, q = _make_hotkey_manager(capture=False, hook=hook, fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    assert hm.on_global_key_press(_f5()) is None
    assert calls == [] and fired == []
    assert q.qsize() == 0


def test_stop_listener_clears_hotkey_down():
    # A focus-out can stop the listener while a bound chord's key is still
    # physically held; _hotkey_down must not wedge across the stop.
    hm, _ = _make_hotkey_manager(fire_hotkeys=True)
    hm.on_global_key_press(_f5())
    assert "F5" in hm._hotkey_down
    hm.is_listening = True
    hm.listener = MagicMock()
    hm._stop_listener()
    assert hm._hotkey_down == set()


def test_bound_chord_autorepeat_fires_once():
    fired = []
    hm, q = _make_hotkey_manager(fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_f5())
    hm.on_global_key_press(_f5())   # OS auto-repeat while still held
    hm.on_global_key_press(_f5())
    assert fired == ["app.refresh"]
    assert q.qsize() == 0


def test_repeat_ok_action_refires_on_autorepeat():
    def hook(mods, keys):
        return ("overlay.scale_up"
                if keys == frozenset({"F5"}) and not mods else None)

    fired = []
    hm, q = _make_hotkey_manager(
        hook=hook, fire_hotkeys=True,
        repeat_ok=frozenset({"overlay.scale_up"}))
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_f5())
    hm.on_global_key_press(_f5())   # auto-repeat: repeat_ok actions re-fire
    assert fired == ["overlay.scale_up", "overlay.scale_up"]
    assert q.qsize() == 0


def test_release_then_press_fires_again():
    fired = []
    hm, q = _make_hotkey_manager(fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_f5())
    hm.on_global_key_release(_f5())
    hm.on_global_key_press(_f5())   # fresh physical press
    assert fired == ["app.refresh", "app.refresh"]
    assert q.qsize() == 0


def _ctrl_chord_hook(calls):
    def hook(mods, keys):
        calls.append((mods, keys))
        if mods == frozenset({"ctrl", "alt"}) and keys == frozenset({"h"}):
            return "overlay.toggle_cards"
        return None
    return hook


def test_ctrl_control_char_maps_to_letter_and_skips():
    # normalize_key yields the control char ('\x08') for ctrl+h; the hook must
    # be consulted with the letter form so the binding table ('h') matches.
    calls, fired = [], []
    hm, q = _make_hotkey_manager(hook=_ctrl_chord_hook(calls),
                                 fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_fake_key(name="ctrl_l"))
    hm.on_global_key_press(_fake_key(name="alt_l"))
    baseline = q.qsize()                              # modifier keydowns enqueue
    hm.on_global_key_press(_fake_key(char="\x08"))    # ctrl+h as control char
    assert (frozenset({"ctrl", "alt"}), frozenset({"h"})) in calls
    assert fired == ["overlay.toggle_cards"]
    assert q.qsize() == baseline                      # chord press skipped
    hm.on_global_key_release(_fake_key(char="\x08"))  # ctrl still held
    assert q.qsize() == baseline                      # release skipped too


def test_ctrl_released_before_letter_release_still_skipped():
    # ctrl may be released BEFORE the letter: the letter's release then arrives
    # as the plain char ('h'), which must still match the tracked press.
    calls = []
    hm, q = _make_hotkey_manager(hook=_ctrl_chord_hook(calls))
    hm.on_global_key_press(_fake_key(name="ctrl_l"))
    hm.on_global_key_press(_fake_key(name="alt_l"))
    hm.on_global_key_press(_fake_key(char="\x08"))    # skipped chord press
    hm.on_global_key_release(_fake_key(name="ctrl_l"))
    hm.on_global_key_release(_fake_key(name="alt_l"))
    baseline = q.qsize()
    hm.on_global_key_release(_fake_key(char="h"))     # plain-form release
    assert q.qsize() == baseline                      # still skipped


def _pair_hook(mods, keys):
    """Bindings: ctrl+1+t (two-key) and bare F5."""
    if mods == frozenset({"ctrl"}) and keys == frozenset({"1", "t"}):
        return "overlay.toggle_cards"
    if keys == frozenset({"F5"}) and not mods:
        return "app.refresh"
    return None


def test_two_key_chord_fires_on_second_key_while_first_held():
    fired = []
    hm, q = _make_hotkey_manager(hook=_pair_hook, fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_fake_key(name="ctrl_l"))
    hm.on_global_key_press(_fake_key(char="\x14"))    # ctrl+t: first member
    assert fired == []                                # partner not yet held
    baseline = q.qsize()   # ctrl + the first member were enqueued (the first
    # member mirrors the X-side replay semantics: it already went to the game)
    hm.on_global_key_press(_fake_key(char="1"))       # second member joins
    assert fired == ["overlay.toggle_cards"]
    assert q.qsize() == baseline                      # firing press skipped
    hm.on_global_key_release(_fake_key(char="1"))     # skipped release
    assert q.qsize() == baseline


def test_single_binding_fires_while_unbound_key_held():
    # Full-set consult misses ({x, F5}), single-set consult hits ({F5}).
    fired = []
    hm, q = _make_hotkey_manager(hook=_pair_hook, fire_hotkeys=True)
    hm.hotkey_triggered.connect(fired.append)
    hm.on_global_key_press(_fake_key(char="x"))       # unbound, stays held
    hm.on_global_key_press(_f5())
    assert fired == ["app.refresh"]


def test_held_keys_cleanup_on_release_and_stop():
    hm, _ = _make_hotkey_manager()
    hm.on_global_key_press(_fake_key(char="x"))
    hm.on_global_key_press(_f5())
    assert hm._held_keys == {"x", "F5"}
    hm.on_global_key_release(_fake_key(char="x"))
    assert hm._held_keys == {"F5"}
    hm.is_listening = True
    hm.listener = MagicMock()
    hm._stop_listener()
    assert hm._held_keys == set()


def test_held_keys_ctrl_mapped_form_cleaned_after_ctrl_release():
    # Press tracked the ctrl-mapped letter ('h'); ctrl releases first, so the
    # key's release surfaces as the raw control char -- the mapped form must
    # still leave the held set.
    hm, _ = _make_hotkey_manager()
    hm.on_global_key_press(_fake_key(name="ctrl_l"))
    hm.on_global_key_press(_fake_key(char="\x08"))    # tracked as 'h'
    assert "h" in hm._held_keys
    hm.on_global_key_release(_fake_key(name="ctrl_l"))
    hm.on_global_key_release(_fake_key(char="\x08"))  # raw form, ctrl gone
    assert hm._held_keys == set()


def test_no_stranded_keyup_when_chord_key_held_past_modifiers():
    # Hold ctrl+alt+h (skipped chord), release the modifiers while KEEPING h
    # held: the next auto-repeat press MISSES the hook and is enqueued as a
    # keydown -- by construction the final physical release must then be
    # enqueued too, or the game is stuck with a stranded held key.
    calls = []
    hm, q = _make_hotkey_manager(hook=_ctrl_chord_hook(calls))
    hm.on_global_key_press(_fake_key(name="ctrl_l"))
    hm.on_global_key_press(_fake_key(name="alt_l"))
    hm.on_global_key_press(_fake_key(char="\x08"))    # chord press: skipped
    hm.on_global_key_release(_fake_key(name="ctrl_l"))
    hm.on_global_key_release(_fake_key(name="alt_l"))
    hm.on_global_key_press(_fake_key(char="h"))       # auto-repeat, no mods
    hm.on_global_key_release(_fake_key(char="h"))     # final physical release
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert ("keydown", "h") in events                 # the miss was enqueued
    assert ("keyup", "h") in events                   # ...and its keyup passed
