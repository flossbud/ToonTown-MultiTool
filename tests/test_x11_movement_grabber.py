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
