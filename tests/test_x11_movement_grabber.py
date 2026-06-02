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


def test_stale_install_action_does_not_survive_stop_and_prepare(fake_display):
    """Regression: stop() enqueues uninstall + shutdown, but a caller may
    have enqueued an install_grabs() between stop() and the thread draining.
    That stale install must NOT fire after a subsequent prepare() call.

    Reproduces the scenario described in the code review:
      prepare() -> install_grabs() -> stop() [thread still draining]
      -> install_grabs() [stale, enqueued after stop]
      -> prepare() [fresh start]
    The fresh prepare must not see the stale install action and must not
    call grab_key on behalf of the previous caller."""
    import time
    d, root = fake_display

    g = grabber_mod.MovementKeyGrabber()

    # First lifecycle: prepare -> install -> stop.
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    time.sleep(0.05)
    g.stop()

    # Enqueue a stale install AFTER stop() returns (thread already exited).
    g._actions.put(("install", "arrows", []))

    # Second lifecycle: prepare should start clean.
    d.reset_mock()
    root.reset_mock()

    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
    # Give the thread time to drain any stale actions.
    time.sleep(0.1)

    # No grab_key calls: the stale "install" must have been cleared.
    assert root.grab_key.call_count == 0, (
        f"Stale install action survived stop+prepare: {root.grab_key.call_count} grabs fired"
    )

    g.stop()


def test_per_action_exception_does_not_kill_thread(fake_display):
    """Regression: if _install_grabs_inline raises (e.g., Xlib error not
    covered by the inner BadAccess catch), the exception must NOT propagate
    through _drain_actions to _run and silently kill the daemon thread.

    After the exception the thread must still be alive, and a subsequent
    uninstall_grabs() action must be processed normally."""
    import time
    d, root = fake_display

    # Make keysym_to_keycode raise to trigger an exception inside
    # _install_grabs_inline (specifically during the grabbed-keysym loop).
    d.keysym_to_keycode.side_effect = RuntimeError("Xlib exploded")

    g = grabber_mod.MovementKeyGrabber()
    g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)

    assert g._thread is not None and g._thread.is_alive()

    # This install will raise inside _install_grabs_inline.
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=[])
    time.sleep(0.1)

    # Thread must still be alive after the exception.
    assert g._thread.is_alive(), "Thread died after exception in _install_grabs_inline"

    # Restore normal behaviour and enqueue an uninstall to prove the thread
    # can still process actions.
    d.keysym_to_keycode.side_effect = lambda ks: 100 + (ks % 50)
    g.uninstall_grabs()
    time.sleep(0.1)

    # Thread must still be alive after the uninstall action.
    assert g._thread.is_alive(), "Thread died after processing uninstall action"

    g.stop()


# ── Regression: held passthrough key auto-repeat release must not stop the toon ──

def _bitvector_with(keycode, down):
    """A 32-byte query_keymap() bit vector with `keycode` set/clear."""
    km = [0] * 32
    if down:
        km[keycode >> 3] |= (1 << (keycode & 7))
    return km


def test_passthrough_autorepeat_release_dropped_when_key_still_down(fake_display):
    """REGRESSION (TTR strict simultaneous control): while a passthrough key
    (the focused toon's WASD) is physically HELD, its X auto-repeat KeyRelease
    can reach the grabber during another key's active grab without the same-time
    matching KeyPress queued. The grabber must NOT forward that as a real keyup
    (which stopped the focused toon). query_keymap shows the key still down ->
    drop it."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_passthrough_calls = []

    from Xlib import XK
    up_ks = XK.string_to_keysym("Up")
    w_ks = XK.string_to_keysym("w")
    d.keysym_to_keycode.side_effect = lambda ks: {up_ks: 111, w_ks: 25}.get(ks, 0)

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 25          # 'w' (passthrough)
    release.time = 5000

    # No same-time matching KeyPress queued (broken pairing).
    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = release
    # 'w' (keycode 25) is still physically down -> this release is auto-repeat.
    d.query_keymap.return_value = _bitvector_with(25, down=True)

    g.prepare(
        on_key=lambda *_: None,
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w"])
    import time
    time.sleep(0.1)
    g.stop()

    assert ("keyup", "w") not in on_passthrough_calls


def test_passthrough_real_release_forwarded_when_key_up(fake_display):
    """Inverse guard: a genuine release (key physically UP per query_keymap) IS
    forwarded once as a keyup, so the focused toon stops when the user really
    lets go."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_passthrough_calls = []

    from Xlib import XK
    up_ks = XK.string_to_keysym("Up")
    w_ks = XK.string_to_keysym("w")
    d.keysym_to_keycode.side_effect = lambda ks: {up_ks: 111, w_ks: 25}.get(ks, 0)

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 25
    release.time = 5000

    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = release
    # 'w' is physically UP -> a real release.
    d.query_keymap.return_value = _bitvector_with(25, down=False)

    g.prepare(
        on_key=lambda *_: None,
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w"])
    import time
    time.sleep(0.1)
    g.stop()

    # Forwarded exactly once (a duplicate keyup would also be a defect).
    assert on_passthrough_calls == [("keyup", "w")]


def test_query_keymap_failure_falls_back_to_real_release(fake_display):
    """Defensive: if query_keymap() raises (or is unavailable), the auto-repeat
    guard must not crash the event-loop thread and must fall back to the prior
    behavior (treat the release as real and forward it)."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()

    on_passthrough_calls = []

    from Xlib import XK
    w_ks = XK.string_to_keysym("w")
    d.keysym_to_keycode.side_effect = lambda ks: {w_ks: 25}.get(ks, 0)

    release = MagicMock()
    release.type = X.KeyRelease
    release.detail = 25
    release.time = 5000

    pending_seq = iter([0, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    d.pending_events.side_effect = lambda: next(pending_seq, 0)
    d.next_event.return_value = release
    d.query_keymap.side_effect = RuntimeError("xlib boom")

    g.prepare(
        on_key=lambda *_: None,
        on_passthrough=lambda a, k: on_passthrough_calls.append((a, k)),
        should_consume=lambda _: True,
    )
    g.install_grabs(canonical_set="wasd", passthrough_keysyms=["w"])
    import time
    time.sleep(0.1)
    # Thread survived the raising query_keymap and forwarded the release.
    assert g._thread.is_alive()
    g.stop()

    assert on_passthrough_calls == [("keyup", "w")]


def test_route_all_grabs_both_keysets_async_owner_false(fake_display):
    d, root = fake_display
    from Xlib import XK
    names = ["w", "a", "s", "d", "Up", "Down", "Left", "Right"]
    keycodes = {n: 100 + i for i, n in enumerate(names)}
    d.keysym_to_keycode.side_effect = (
        lambda ks: next((kc for n, kc in keycodes.items()
                         if XK.string_to_keysym(n) == ks), 0))
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
        g.install_grabs(canonical_set="wasd", route_all=True)
        import time; time.sleep(0.1)
        grabbed = {c.args[0] for c in root.grab_key.call_args_list}
        assert grabbed == set(keycodes.values())            # all 8, both sets
        sample = root.grab_key.call_args_list[0]
        assert sample.args[2] is False                       # owner_events
        assert sample.args[4] == grabber_mod.X.GrabModeAsync # keyboard mode
    finally:
        g.stop()


def test_failed_route_all_then_cc_install_clears_stale_state(fake_display):
    """Regression: an all-BadAccess route_all install leaves _grabbed empty but
    _keycode_to_name populated and _route_all=True.  A subsequent CC install must
    NOT skip the pre-install cleanup just because _grabbed is empty.

    Proves:
      (a) _route_all is False after the CC install (mode was reset)
      (b) No wasd keycodes remain classified as 'grabbed' - only the CC
          conflicting set (arrows, when canonical=wasd) should be grabbed.
    """
    import time
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)

        # Make every grab_key call raise BadAccess to simulate all-failed
        # route_all install (e.g. another process holds an exclusive grab).
        root.grab_key.side_effect = grabber_mod.BadAccess.__new__(grabber_mod.BadAccess)
        g.install_grabs(canonical_set="wasd", route_all=True)
        time.sleep(0.1)

        # Confirm we're in the poisoned state: _route_all True, _grab_ok False.
        assert g._route_all is True
        assert g._grab_ok is False
        # _keycode_to_name must be populated (all 8 movement keycodes were
        # registered before the grab attempt, even though grabs all failed).
        assert len(g._keycode_to_name) == 8, (
            f"Expected 8 keycode_to_name entries after all-failed route_all, "
            f"got {len(g._keycode_to_name)}: {g._keycode_to_name}"
        )

        # Now a CC install - grabs succeed again.
        root.grab_key.side_effect = None
        g.install_grabs(canonical_set="wasd")   # route_all defaults False
        time.sleep(0.1)

        # (a) mode must be reset.
        assert g._route_all is False, "_route_all must be False after CC install"

        # (b) Only the CC conflicting keyset (Up/Down/Left/Right for wasd
        # canonical) should be "grabbed".  The wasd keycodes that were
        # spuriously populated by the failed route_all install must be gone.
        from Xlib import XK
        wasd_keycodes = {
            d.keysym_to_keycode(XK.string_to_keysym(n))
            for n in ("w", "a", "s", "d")
        }
        arrow_keycodes = {
            d.keysym_to_keycode(XK.string_to_keysym(n))
            for n in ("Up", "Down", "Left", "Right")
        }
        grabbed_kcs = {
            kc for kc, (kind, _) in g._keycode_to_name.items()
            if kind == "grabbed"
        }
        # Arrow keys must be grabbed (CC conflicting set).
        assert grabbed_kcs == arrow_keycodes, (
            f"CC install should grab only arrow keycodes {arrow_keycodes}, "
            f"got {grabbed_kcs}"
        )
        # WASD keycodes must not be present at all (stale from failed route_all).
        stale = wasd_keycodes & set(g._keycode_to_name.keys())
        assert not stale, (
            f"Stale wasd keycodes from failed route_all still in "
            f"_keycode_to_name after CC install: {stale}"
        )
    finally:
        g.stop()


def test_route_all_reinstall_same_mode_is_noop_even_if_canonical_differs(fake_display):
    """Switching focus between two TTR toons (wasd <-> arrows) must NOT
    re-grab: route_all grabs both keysets regardless of canonical, and a
    re-grab would drain a still-held key and stop the toon."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(on_key=lambda *_: None, should_consume=lambda _: True)
        g.install_grabs(canonical_set="wasd", route_all=True)
        import time; time.sleep(0.1)
        first = root.grab_key.call_count
        g.install_grabs(canonical_set="arrows", route_all=True)  # other TTR toon
        time.sleep(0.1)
        assert root.grab_key.call_count == first  # no re-grab
        assert root.ungrab_key.call_count == 0    # no drain/uninstall
    finally:
        g.stop()


# ── Task 2: route_all event handling ──────────────────────────────────────────

def _route_all_ready(fake_display, on_key, physically_down):
    """A prepared route_all grabber with keycodes registered, _handle_event_
    route_all callable directly. physically_down(kc)->bool stubs query_keymap."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g._on_key = on_key
    g._route_all = True
    g._keycode_to_name = {100: ("grabbed", "w"), 101: ("grabbed", "a")}
    g._key_physically_down = physically_down
    return g


def _ev(etype, detail, t=0):
    from unittest.mock import MagicMock
    e = MagicMock(); e.type = etype; e.detail = detail; e.time = t
    return e


def test_route_all_real_press_and_release(fake_display):
    calls = []
    g = _route_all_ready(fake_display, lambda a, k: calls.append((a, k)),
                         physically_down=lambda kc: False)
    g._handle_event_route_all(_ev(X.KeyPress, 100))
    g._handle_event_route_all(_ev(X.KeyRelease, 100))  # physically up -> real
    assert calls == [("keydown", "w"), ("keyup", "w")]


def test_route_all_autorepeat_release_kept_held(fake_display):
    calls = []
    g = _route_all_ready(fake_display, lambda a, k: calls.append((a, k)),
                         physically_down=lambda kc: True)  # still down = autorepeat
    g._handle_event_route_all(_ev(X.KeyPress, 100))
    g._handle_event_route_all(_ev(X.KeyRelease, 100))  # autorepeat -> dropped
    assert calls == [("keydown", "w")]
    assert 100 in g._held


def test_route_all_autorepeat_press_not_redundant_keydown(fake_display):
    calls = []
    g = _route_all_ready(fake_display, lambda a, k: calls.append((a, k)),
                         physically_down=lambda kc: True)
    g._handle_event_route_all(_ev(X.KeyPress, 100))
    g._handle_event_route_all(_ev(X.KeyPress, 100))  # autorepeat press
    assert calls == [("keydown", "w")]


def test_route_all_unheld_release_ignored(fake_display):
    calls = []
    g = _route_all_ready(fake_display, lambda a, k: calls.append((a, k)),
                         physically_down=lambda kc: False)
    g._handle_event_route_all(_ev(X.KeyRelease, 100))  # never pressed
    assert calls == []


def test_route_all_uninstall_drains_held(fake_display):
    """ORDERING: the drain keyup (on_key "keyup") must fire BEFORE
    root.ungrab_key is called. Grabs must still be active when on_key fires
    so InputService can synthesize to the still-suppressed focused window."""
    d, root = fake_display
    order = []
    g = grabber_mod.MovementKeyGrabber()
    g._on_key = lambda a, k: order.append(("on_key", a, k))
    g._route_all = True
    g._display = d; g._root = root
    g._keycode_to_name = {100: ("grabbed", "w")}
    g._grabbed = [(100, 0)]
    g._held = {100}

    # Record the call order via side_effect on ungrab_key.
    _orig_ungrab = root.ungrab_key
    def _recording_ungrab(kc, mod):
        order.append(("ungrab_key", kc, mod))
        return _orig_ungrab(kc, mod)
    root.ungrab_key.side_effect = _recording_ungrab

    calls = [(e[1], e[2]) for e in order if e[0] == "on_key"]
    g._uninstall_grabs_inline()

    # Gather on_key and ungrab_key positions in the order list.
    on_key_positions = [i for i, e in enumerate(order) if e[0] == "on_key"]
    ungrab_positions  = [i for i, e in enumerate(order) if e[0] == "ungrab_key"]

    assert ("keyup", "w") in [(e[1], e[2]) for e in order if e[0] == "on_key"], (
        "drain keyup for 'w' must be emitted"
    )
    assert on_key_positions, "on_key was never called"
    assert ungrab_positions, "ungrab_key was never called"
    assert max(on_key_positions) < min(ungrab_positions), (
        "on_key (drain keyup) must fire before any ungrab_key call; "
        f"on_key positions={on_key_positions}, ungrab positions={ungrab_positions}"
    )
    assert g._held == set()


# ── Task 3B: route_all passthrough re-delivery ────────────────────────────────

def test_route_all_install_registers_passthrough_without_grabbing(fake_display):
    """route_all grabs the 8 movement keys AND registers passthrough keysyms
    (recognized but NOT grabbed) so they can be re-delivered when redirected."""
    d, root = fake_display
    from Xlib import XK
    names = {"w": 100, "a": 101, "s": 102, "d": 103,
             "Up": 111, "Down": 116, "Left": 113, "Right": 114, "j": 150}
    d.keysym_to_keycode.side_effect = (
        lambda ks: next((kc for n, kc in names.items()
                         if XK.string_to_keysym(n) == ks), 0))
    g = grabber_mod.MovementKeyGrabber()
    try:
        g.prepare(on_key=lambda *_: None, should_consume=lambda _: True,
                  on_passthrough=lambda *_: None)
        g.install_grabs(canonical_set="wasd", passthrough_keysyms=["j"], route_all=True)
        import time; time.sleep(0.1)
        assert g._keycode_to_name.get(150) == ("passthrough", "j")
        grabbed = {c.args[0] for c in root.grab_key.call_args_list}
        assert 150 not in grabbed                 # passthrough key not grabbed
        assert 100 in grabbed and 111 in grabbed  # movement keys grabbed
    finally:
        g.stop()


def test_route_all_passthrough_key_calls_on_passthrough(fake_display):
    """A non-movement key event (arrives only via the active-grab redirect)
    is re-delivered through on_passthrough, NOT dropped, NOT via on_key."""
    d, root = fake_display
    pt, ok = [], []
    g = grabber_mod.MovementKeyGrabber()
    g._on_passthrough = lambda a, k: pt.append((a, k))
    g._on_key = lambda a, k: ok.append((a, k))
    g._route_all = True
    g._keycode_to_name = {150: ("passthrough", "j")}
    g._handle_event_route_all(_ev(X.KeyPress, 150))
    g._handle_event_route_all(_ev(X.KeyRelease, 150))
    assert pt == [("keydown", "j"), ("keyup", "j")]
    assert ok == []
    assert 150 not in g._held


def test_route_all_rapid_tap_adjacent_press_keeps_held(fake_display):
    """Rapid-tap / adjacent-press behavior under query_keymap-Async contract.

    When a KeyRelease arrives but query_keymap reports the key STILL
    physically down, _handle_event_route_all treats it as an autorepeat-or-
    rapid-tap artifact and keeps the keycode in _held without emitting a
    keyup. Only when query_keymap subsequently reports the key UP is the
    real keyup emitted and the key removed from _held.

    This is the accepted behavior under GrabModeAsync where the XServer
    does not freeze keyboard delivery between events. A 'rapid tap'
    (human tap shorter than a typical query_keymap poll window) may look
    identical to an autorepeat release and is handled identically here:
    the held state lingers until the next release with the key physically
    up. The practical effect is at most one extra autorepeat cycle of
    delay between the real physical release and the simulated keyup --
    acceptable given that the alternative (treating every release as real)
    causes spurious mid-hold keyup spikes that stop the toon."""
    calls = []
    # First pass: physically down => autorepeat/rapid-tap: stay held, no keyup.
    g = _route_all_ready(fake_display, lambda a, k: calls.append((a, k)),
                         physically_down=lambda kc: True)
    g._handle_event_route_all(_ev(X.KeyPress, 100))       # keydown
    g._handle_event_route_all(_ev(X.KeyRelease, 100))     # physically still down -> kept held
    assert calls == [("keydown", "w")]
    assert 100 in g._held

    # Second pass: physically up => real release: keyup emitted, removed from held.
    g._key_physically_down = lambda kc: False
    g._handle_event_route_all(_ev(X.KeyRelease, 100))     # now really up
    assert calls == [("keydown", "w"), ("keyup", "w")]
    assert 100 not in g._held


def test_route_all_passthrough_none_callback_no_raise(fake_display):
    """A passthrough event arriving when _on_passthrough is None (e.g.
    prepare() was called without on_passthrough) must not raise."""
    d, root = fake_display
    g = grabber_mod.MovementKeyGrabber()
    g._on_passthrough = None     # explicitly unset
    g._on_key = lambda *_: None
    g._route_all = True
    g._keycode_to_name = {150: ("passthrough", "j")}
    # Must not raise.
    g._handle_event_route_all(_ev(X.KeyPress, 150))
    g._handle_event_route_all(_ev(X.KeyRelease, 150))
