"""Unit tests for utils.x11_movement_grabber.

The X11 surface is mocked. An integration test against a real X display
would be useful but is environment-dependent; this file verifies the
wrapper makes the right Xlib calls and exposes the right lifecycle.
"""

import sys
import threading
from unittest.mock import MagicMock

import pytest

xlib = pytest.importorskip("Xlib")
from Xlib import X

from utils import x11_movement_grabber as grabber_mod


@pytest.fixture
def fake_display(monkeypatch):
    """Replace Xlib.display.Display with a MagicMock so the grabber never
    opens a real X connection."""
    d = MagicMock()
    root = MagicMock()
    d.screen.return_value.root = root
    d.keysym_to_keycode.side_effect = lambda ks: 100 + (ks % 50)
    d.pending_events.return_value = 0
    monkeypatch.setattr(grabber_mod._xlib_display, "Display", lambda: d)
    return d, root


def test_start_returns_false_when_xlib_unavailable(monkeypatch):
    monkeypatch.setattr(grabber_mod, "_HAS_XLIB", False)
    g = grabber_mod.MovementKeyGrabber()
    assert g.start(["Up"], on_key=lambda *_: None, should_consume=lambda _: True) is False


def test_start_grabs_each_keysym_with_lock_modifier_permutations(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        ok = g.start(
            keysyms=["Up", "Down"],
            on_key=lambda *_: None,
            should_consume=lambda _: True,
        )
        assert ok
        # 2 keysyms x 8 lock-combinations = 16 grabs.
        assert root.grab_key.call_count == 2 * len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_start_skips_unknown_keysyms(fake_display, capsys):
    d, root = fake_display
    # XK.string_to_keysym returns 0 for unknown names.
    from Xlib import XK
    real = XK.string_to_keysym
    def fake_string_to_keysym(name):
        if name == "Unknownnnnn":
            return 0
        return real(name)
    import utils.x11_movement_grabber as gm
    gm.XK.string_to_keysym = fake_string_to_keysym

    g = grabber_mod.MovementKeyGrabber()
    try:
        ok = g.start(keysyms=["Unknownnnnn", "Up"], on_key=lambda *_: None, should_consume=lambda _: True)
        assert ok
        # Only Up gets grabbed (8 combos).
        assert root.grab_key.call_count == len(grabber_mod._LOCK_MODIFIERS)
        out = capsys.readouterr().out
        assert "unknown keysym" in out
    finally:
        g.stop()
        gm.XK.string_to_keysym = real


def test_stop_ungrabs_each_registered_combo(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.start(keysyms=["Up"], on_key=lambda *_: None, should_consume=lambda _: True)
    grabbed_count = root.grab_key.call_count
    g.stop()
    assert root.ungrab_key.call_count == grabbed_count


def test_event_consume_path_calls_on_key_and_async_allow(fake_display):
    """Build one KeyPress event; should_consume returns True; verify
    on_key fires AND allow_events(AsyncKeyboard, time) is sent."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []
    consume_calls = []
    consume_decision = True

    def on_key(action, ks):
        on_key_calls.append((action, ks))

    def should_consume(ks):
        consume_calls.append(ks)
        return consume_decision

    # Stub keysym_to_keycode so registering "Up" produces keycode 111,
    # then send an event with detail=111 so the grabber's keycode->name
    # lookup finds "Up".
    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 111
    event.time = 1234

    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.start(keysyms=["Up"], on_key=on_key, should_consume=should_consume)
    # Let the thread run briefly.
    import time
    time.sleep(0.1)
    g.stop()

    assert ("keydown", "Up") in on_key_calls
    assert consume_calls == ["Up"]
    # AsyncKeyboard call: 4th positional arg to allow_events is the mode.
    modes_used = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.AsyncKeyboard in modes_used


def test_event_replay_path_does_not_call_on_key(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 111
    event.time = 1234

    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.start(
        keysyms=["Up"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: False,
    )
    import time
    time.sleep(0.1)
    g.stop()

    assert on_key_calls == []
    modes_used = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.ReplayKeyboard in modes_used


def test_double_start_is_idempotent(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.start(keysyms=["Up"], on_key=lambda *_: None, should_consume=lambda _: True)
    first_grab_count = root.grab_key.call_count
    g.start(keysyms=["Up"], on_key=lambda *_: None, should_consume=lambda _: True)
    assert root.grab_key.call_count == first_grab_count
    g.stop()


def test_double_stop_is_idempotent(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.start(keysyms=["Up"], on_key=lambda *_: None, should_consume=lambda _: True)
    g.stop()
    g.stop()  # must not raise


def test_autorepeat_pair_is_dropped(fake_display):
    """X11 represents auto-repeat as KeyRelease+KeyPress at same time on
    the same key. The grabber must drop both halves and NOT fire on_key,
    so the bridge doesn't spam press/release cycles to the routed toon."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 111
    release.time = 5000

    press = MagicMock()
    press.type = X.KeyPress
    press.detail = 111
    press.time = 5000  # SAME time as release - auto-repeat signature

    # pending_events sequence: 1 (for release), then 1 (for the peek inside
    # the autorepeat branch), then 0 to let the loop exit.
    pending_seq = iter([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    # next_event returns release first, then press.
    d.next_event.side_effect = [release, press]

    g.start(
        keysyms=["Up"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    import time
    time.sleep(0.1)
    g.stop()

    # Auto-repeat: both events dropped, no callback fires.
    assert on_key_calls == []


def test_release_not_auto_repeat_is_processed_normally(fake_display):
    """If a KeyRelease isn't followed by a same-time KeyPress, treat it
    as a real release: fire on_key for the keyup."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 111
    release.time = 5000

    # Next event is a DIFFERENT key at a different time. Not auto-repeat.
    other = MagicMock()
    other.type = X.KeyPress
    other.detail = 999
    other.time = 6000

    pending_seq = iter([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.side_effect = [release, other]

    g.start(
        keysyms=["Up"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    import time
    time.sleep(0.1)
    g.stop()

    # Release was processed; on_key called with "keyup" for Up.
    assert ("keyup", "Up") in on_key_calls


def test_release_with_no_pending_is_processed_normally(fake_display):
    """KeyRelease with no follow-up event in queue should fire on_key
    for the keyup. Without this case, real releases would never reach
    the routing layer."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 111
    release.time = 5000

    # pending_events: 1 (the release), then 0 (no peek-target), then 0...
    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = release

    g.start(
        keysyms=["Up"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    import time
    time.sleep(0.1)
    g.stop()

    assert ("keyup", "Up") in on_key_calls


def test_passthrough_keysyms_register_but_dont_install_grabs(fake_display):
    """Passthrough keysyms get a keycode mapping but no XGrabKey calls.
    A grabbed key still gets its 8 lock-modifier combos."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        ok = g.start(
            keysyms=["Up"],
            passthrough_keysyms=["w", "a"],
            on_key=lambda *_: None,
            on_passthrough=lambda *_: None,
            should_consume=lambda _: True,
        )
        assert ok
        # Only Up gets grabbed (1 keysym * 8 lock combos), w/a get no grabs.
        assert root.grab_key.call_count == len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_passthrough_event_fires_on_passthrough_not_on_key(fake_display):
    """When a passthrough key event arrives during the active grab,
    on_passthrough fires with (action, keysym) and on_key is skipped."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []
    on_passthrough_calls = []

    from Xlib import XK
    up_ks = XK.string_to_keysym("Up")
    w_ks = XK.string_to_keysym("w")
    d.keysym_to_keycode.side_effect = lambda ks: {up_ks: 111, w_ks: 25}.get(ks, 0)

    # One W KeyPress event (simulating W arriving during Up's active grab).
    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 25
    event.time = 1234

    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.start(
        keysyms=["Up"],
        passthrough_keysyms=["w"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    import time
    time.sleep(0.1)
    g.stop()

    assert on_passthrough_calls == [("keydown", "w")]
    assert on_key_calls == []


def test_modifier_combos_cover_shift_ctrl_alt(fake_display):
    """The modifier set must include masks for Shift, Ctrl, and Alt so
    grabs fire even when the user is holding a modifier (e.g. Shift+Up
    for sprint-forward)."""
    assert X.ShiftMask in grabber_mod._LOCK_MODIFIERS
    assert X.ControlMask in grabber_mod._LOCK_MODIFIERS
    assert X.Mod1Mask in grabber_mod._LOCK_MODIFIERS  # Alt
    # Combined: Shift+Ctrl, Shift+Alt, Ctrl+Alt
    assert (X.ShiftMask | X.ControlMask) in grabber_mod._LOCK_MODIFIERS
    assert (X.ShiftMask | X.Mod1Mask) in grabber_mod._LOCK_MODIFIERS
    # And mixed with lock keys
    assert (X.ShiftMask | X.LockMask) in grabber_mod._LOCK_MODIFIERS


def test_modifier_combos_has_64_entries(fake_display):
    """8 lock combos x 8 user-modifier combos = 64 unique masks."""
    assert len(grabber_mod._LOCK_MODIFIERS) == 64


def test_grabbed_key_with_consume_false_falls_through_to_passthrough(fake_display):
    """When should_consume returns False for a grabbed key (e.g. chat is
    active), the event should still fire on_passthrough so the focused
    window's chat box receives the arrow for cursor movement."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_key_calls = []
    on_passthrough_calls = []

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: 111 if ks == XK.string_to_keysym("Up") else 0

    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 111
    event.time = 1234

    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.start(
        keysyms=["Up"],
        on_key=lambda a, k: on_key_calls.append((a, k)),
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: False,  # e.g. chat active
    )
    import time
    time.sleep(0.1)
    g.stop()

    assert on_key_calls == []
    assert on_passthrough_calls == [("keydown", "Up")]


def test_grab_key_uses_sync_keyboard_mode(fake_display):
    """ReplayKeyboard is a no-op under GrabModeAsync. The grabber MUST
    register with GrabModeSync so the non-consume path actually re-delivers
    arrow events to the focused window (TTR, Firefox, terminals, etc.)."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.start(
            keysyms=["Up"],
            on_key=lambda *_: None,
            should_consume=lambda _: True,
        )
        # grab_key positional args: keycode, modifiers, owner_events,
        # pointer_mode, keyboard_mode. We care about keyboard_mode.
        for call in root.grab_key.call_args_list:
            args = call.args
            assert args[4] == X.GrabModeSync, (
                f"keyboard_mode must be GrabModeSync, got {args[4]}"
            )
    finally:
        g.stop()


def test_passthrough_event_uses_replay_keyboard_mode(fake_display):
    """Passthrough events should use ReplayKeyboard so X is told to let
    the event flow normally (even though Replay is a no-op in async)."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: {XK.string_to_keysym("Up"): 111, XK.string_to_keysym("w"): 25}.get(ks, 0)

    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 25
    event.time = 1234

    pending_seq = iter([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.start(
        keysyms=["Up"],
        passthrough_keysyms=["w"],
        on_key=lambda *_: None,
        on_passthrough=lambda *_: None,
        should_consume=lambda _: True,
    )
    import time
    time.sleep(0.1)
    g.stop()

    modes = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.ReplayKeyboard in modes
