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


def test_prepare_returns_false_when_xlib_unavailable(monkeypatch):
    monkeypatch.setattr(grabber_mod, "_HAS_XLIB", False)
    g = grabber_mod.MovementKeyGrabber()
    assert g.prepare(on_key=lambda *_: None, should_consume=lambda _: True) is False


def test_prepare_opens_display_but_does_not_install_grabs(fake_display):
    """prepare() establishes the Xlib connection and starts the event
    loop, but installs zero grabs. install_grabs() must be called next."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        ok = g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        assert ok
        # No grabs yet.
        assert root.grab_key.call_count == 0
    finally:
        g.stop()


def test_install_grabs_wasd_grabs_arrow_keys(fake_display):
    """install_grabs('wasd') registers passive grabs on Up/Down/Left/Right
    (the conflicting keyset when canonical=WASD). 4 keysyms x 64 modifier
    combos = 256 grab_key calls."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w", "a", "s", "d"])
        # Drain the action queue: event thread polls; give it a beat.
        import time; time.sleep(0.1)
        assert root.grab_key.call_count == 4 * len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_install_grabs_arrows_grabs_wasd_keys(fake_display):
    """install_grabs('arrows') grabs WASD instead (focused toon is on the
    arrows set, so suppress the WASD bleed-through)."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        g.install_grabs(canonical_set="arrows", passthrough_keysyms=["Up", "Down", "Left", "Right"])
        import time; time.sleep(0.1)
        assert root.grab_key.call_count == 4 * len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_uninstall_grabs_releases_every_registered_combo(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        grabbed = root.grab_key.call_count
        g.uninstall_grabs()
        import time; time.sleep(0.1)
        assert root.ungrab_key.call_count == grabbed
    finally:
        g.stop()


def test_install_then_install_different_set_swaps_grabs(fake_display):
    """Changing canonical_set from wasd to arrows uninstalls the old grabs
    and installs the new ones."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        first = root.grab_key.call_count
        g.install_grabs(canonical_set="arrows", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        # All old grabs ungrabbed, new set installed (same count).
        assert root.ungrab_key.call_count == first
        assert root.grab_key.call_count == 2 * first
    finally:
        g.stop()


def test_install_same_set_twice_is_noop(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
            on_passthrough=lambda *_: None,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        first = root.grab_key.call_count
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        assert root.grab_key.call_count == first
        assert root.ungrab_key.call_count == 0
    finally:
        g.stop()


def test_grab_uses_all_keysyms_in_canonical_set(fake_display):
    """prepare() + install_grabs('wasd') grabs exactly 4 keysyms
    (Up/Down/Left/Right) each with the full modifier permutation set."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        # 4 keysyms x 64 modifier combos = 256 grabs.
        assert root.grab_key.call_count == 4 * len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_keysym_with_zero_keycode_is_skipped(fake_display):
    """If keysym_to_keycode returns 0 for a keysym, that keysym is skipped
    and does not produce any grab_key calls. The grabber still works for
    any keysyms that have valid keycodes."""
    d, root = fake_display
    from Xlib import XK
    # Return 0 for Up and Down, valid codes for Left and Right.
    up_ks = XK.string_to_keysym("Up")
    down_ks = XK.string_to_keysym("Down")

    def kc_side_effect(ks):
        if ks in (up_ks, down_ks):
            return 0
        return 100 + (ks % 50)

    d.keysym_to_keycode.side_effect = kc_side_effect

    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
        # Only Left and Right have valid keycodes.
        assert root.grab_key.call_count == 2 * len(grabber_mod._LOCK_MODIFIERS)
    finally:
        g.stop()


def test_stop_ungrabs_each_registered_combo(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time; time.sleep(0.05)
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

    # Start with 0 so the event thread drains the install action first,
    # then return 1 to deliver the event once grabs are registered.
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.prepare(on_key=on_key, should_consume=should_consume)
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
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

    # Start with 0 so the event thread drains the install action first.
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: False,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time
    time.sleep(0.1)
    g.stop()

    assert on_key_calls == []
    modes_used = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.ReplayKeyboard in modes_used


def test_double_prepare_is_idempotent(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time; time.sleep(0.05)
    first_grab_count = root.grab_key.call_count
    # Second prepare while running should be a no-op.
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time; time.sleep(0.05)
    assert root.grab_key.call_count == first_grab_count
    g.stop()


def test_double_stop_is_idempotent(fake_display):
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
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

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
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

    # Start with 0 so the event thread drains the install action first.
    pending_seq = iter([0, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.side_effect = [release, other]

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
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

    # Start with 0 so the event thread drains the install action first,
    # then 1 (the release), then 0 (no peek-target).
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = release

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time
    time.sleep(0.1)
    g.stop()

    assert ("keyup", "Up") in on_key_calls


def test_passthrough_keysyms_register_but_dont_install_grabs(fake_display):
    """Passthrough keysyms get a keycode mapping but no XGrabKey calls.
    The grabbed keysyms (the conflicting set) get the full modifier
    permutation grabs."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            on_passthrough=lambda *_: None,
            should_consume=lambda _: True,
        )
        g.install_grabs(
            canonical_set="wasd",
            passthrough_keysyms=["w", "a"],
        )
        import time; time.sleep(0.1)
        # Only the 4 conflicting keys (Up/Down/Left/Right) get grabs.
        # w and a are passthrough-only - no XGrabKey for them.
        assert root.grab_key.call_count == 4 * len(grabber_mod._LOCK_MODIFIERS)
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

    # Start with 0 so the event thread drains the install action first.
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w"])
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


def test_grabbed_key_with_consume_false_does_not_call_passthrough(fake_display):
    """When should_consume returns False for a grabbed key (e.g. chat is
    active and arrows should reach the focused chat box for cursor
    movement), the grabber must NOT call on_passthrough. Under
    GrabModeSync, allow_events(ReplayKeyboard) re-delivers the original
    event to the focused window naturally; calling on_passthrough would
    double-deliver via the bridge."""
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

    # Start with 0 so the event thread drains the install action first.
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.prepare(
        on_key=lambda a, k: on_key_calls.append((a, k)),
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: False,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    import time
    time.sleep(0.1)
    g.stop()

    assert on_key_calls == []
    assert on_passthrough_calls == []
    # Replay was requested so the focused window receives the event.
    modes_used = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.ReplayKeyboard in modes_used


def test_grab_key_uses_sync_keyboard_mode(fake_display):
    """ReplayKeyboard is a no-op under GrabModeAsync. The grabber MUST
    register with GrabModeSync so the non-consume path actually re-delivers
    arrow events to the focused window (TTR, Firefox, terminals, etc.)."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(
            on_key=lambda *_: None,
            should_consume=lambda _: True,
        )
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
        import time; time.sleep(0.1)
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
    """Passthrough events should use ReplayKeyboard so X re-delivers
    the event to the focused window."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    from Xlib import XK
    d.keysym_to_keycode.side_effect = lambda ks: {XK.string_to_keysym("Up"): 111, XK.string_to_keysym("w"): 25}.get(ks, 0)

    event = MagicMock()
    event.type = X.KeyPress
    event.detail = 25
    event.time = 1234

    # Start with 0 so the event thread drains the install action first.
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = event

    g.prepare(
        on_key=lambda *_: None,
        on_passthrough=lambda *_: None,
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w"])
    import time
    time.sleep(0.1)
    g.stop()

    modes = [c.args[0] for c in d.allow_events.call_args_list]
    assert X.ReplayKeyboard in modes
