"""A stopped session leaves the focused game window playable.

"Stop all toons" must behave, for the window the user is playing in, as if
this app were not there. The router re-delivers a grabbed key only to an
ENABLED toon, so reporting every toon as not enabled is not enough on its
own: with the grabs still installed the focused window's movement keys would
be taken and dropped. The session therefore suspends routing (no grabs)
while stopped.

These run the REAL InputService focus/grab logic and router against a
recording grabber and backend. They are construction checks: the grab itself
is an X11 / Win32 / macOS mechanism that only a live run exercises.
"""

from types import SimpleNamespace

import pytest

from tests.toon_session_harness import Rig


class RecordingGrabber:
    """Stands in for the platform key grabber; reports back like the real one."""

    def __init__(self, service, log):
        self._service = service
        self._log = log
        self.installed = None

    def install_grabs(self, canonical_set=None, passthrough_keysyms=None,
                      route_all=False, route_keys=None):
        self.installed = canonical_set
        self._log.append(("install", canonical_set, bool(route_all)))
        self._service._on_grabs_changed(canonical_set)

    def uninstall_grabs(self):
        self.installed = None
        self._log.append(("uninstall",))
        self._service._on_grabs_changed(None)

    def stop(self):
        self._log.append(("grabber-stop",))


@pytest.fixture
def stage(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TTMT_CHAT_FSM", "1")
    monkeypatch.setattr("sys.platform", "linux")
    from utils.game_registry import GameRegistry
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                        lambda wid: "ttr")
    log = []
    sent = []

    def real_input_service(**kwargs):
        from services.input_service import InputService
        service = InputService(**kwargs)
        service._xlib = SimpleNamespace(disconnect=lambda: None)   # a usable backend
        service._xlib_backend_failed = False
        service._key_grabber = RecordingGrabber(service, log)
        service._send_via_backend = (
            lambda action, win, keysym, modifiers=None: sent.append(
                (action, str(win), keysym)))
        service._resolve_keysym = lambda key: key
        release = service.release_all_keys

        def recorded_release():
            log.append(("release-all",))
            release()

        service.release_all_keys = recorded_release
        return service

    monkeypatch.setattr("tests.toon_session_harness.StubInputService",
                        real_input_service)
    rig = Rig(tmp_path, windows=["a", "b"])
    rig.log, rig.sent = log, sent
    yield rig
    rig.input._key_grabber = None                # nothing real to tear down
    rig.close()


def focus(rig, window_id):
    rig.wm.active = window_id
    rig.input._on_active_window_changed_for_grabber(window_id or "")


def press_forward(rig):
    """What the router does with a grabbed forward key."""
    service = rig.input
    key = rig.keymaps.get_key_for_action("ttr", 0, "forward")
    enabled = service.get_enabled_toons()
    del rig.sent[:]
    service._send_logical_action_km(
        "keydown", key, enabled, service._get_assignments(enabled))
    return list(rig.sent)


def test_running_baseline_grabs_the_focused_window_and_redelivers(stage):
    focus(stage, "a")
    assert stage.log[-1][0] == "install" and stage.log[-1][2] is True
    assert stage.input._strict_ttr_active() is True
    assert {win for _action, win, _key in press_forward(stage)} == {"a", "b"}


def test_a_grabbed_key_is_never_redelivered_to_a_toon_that_is_not_enabled(stage):
    """Why "every toon not enabled" alone would not do: the grab stays, and
    the focused toon's own key is dropped."""
    stage.session.set_enabled("a", False)
    focus(stage, "a")
    assert stage.input._key_grabber.installed is not None
    assert {win for _action, win, _key in press_forward(stage)} == {"b"}


def test_stop_removes_the_grabs_from_the_focused_window(stage):
    focus(stage, "a")
    del stage.log[:]
    stage.session.stop()
    assert stage.log[0] == ("release-all",)          # held keys go up first
    assert stage.log[-1] == ("uninstall",)
    assert not [entry for entry in stage.log if entry[0] == "install"]
    assert stage.input._key_grabber.installed is None
    assert stage.input._ttr_grabs_active is False
    assert stage.input._strict_ttr_active() is False


def test_no_grab_is_installed_while_stopped_whatever_gets_focus(stage):
    stage.session.stop()
    del stage.log[:]
    for window_id in ("a", "b", "", "a"):
        focus(stage, window_id)
    assert all(entry == ("uninstall",) for entry in stage.log)
    assert stage.input._key_grabber.installed is None


def test_nothing_is_synthesized_to_any_window_while_stopped(stage):
    focus(stage, "a")
    stage.session.stop()
    assert stage.input.get_enabled_toons() == [False] * 4
    assert press_forward(stage) == []


def test_stopped_means_native_keys_for_the_focused_window(stage):
    """The two halves together: no grab withholds the key, and the router
    adds nothing of its own. The window sees exactly what the user pressed."""
    focus(stage, "a")
    stage.session.stop()
    focus(stage, "b")                            # alt-tab to the other toon
    assert stage.input._key_grabber.installed is None
    assert stage.input._suppress_predicate("Up") is False
    assert press_forward(stage) == []


def test_held_keys_are_released_while_the_toons_still_read_as_enabled(stage):
    """A hold with no delivery record is released by re-translating the key
    for the enabled toons, so the release must come before they read as not
    enabled, or a background toon is left with a key down."""
    seen = []
    release = stage.input.release_all_keys

    def spy():
        seen.append(list(stage.input.get_enabled_toons()))
        release()

    stage.input.release_all_keys = spy
    stage.session.stop()
    assert seen == [[True, True, False, False]]
    assert stage.input.get_enabled_toons() == [False] * 4


def test_start_reinstalls_the_grabs_for_the_window_in_focus(stage):
    focus(stage, "a")
    stage.session.stop()
    focus(stage, "b")
    del stage.log[:]
    stage.session.start()
    assert stage.log[-1][0] == "install"
    assert stage.input._strict_ttr_active() is True
    assert {win for _action, win, _key in press_forward(stage)} == {"a", "b"}


def test_start_with_no_game_window_in_focus_installs_nothing(stage):
    stage.session.stop()
    focus(stage, "")
    del stage.log[:]
    stage.session.start()
    assert stage.log == [("uninstall",)]


def test_suspending_twice_or_resuming_twice_does_nothing_more(stage):
    focus(stage, "a")
    service = stage.input
    service.set_routing_suspended(True)
    del stage.log[:]
    service.set_routing_suspended(True)
    assert stage.log == []
    service.set_routing_suspended(False)
    del stage.log[:]
    service.set_routing_suspended(False)
    assert stage.log == []


def test_an_input_service_is_not_suspended_unless_asked(stage):
    """The Multitoon tab never calls set_routing_suspended: unchanged for it."""
    assert stage.input._routing_suspended is False


# ── Non-exclusive grabbers (Windows, macOS) ─────────────────────────────────
#
# There the hook withholds only the keys the grabber's should_suppress says
# yes to, and every other key reaches the focused window natively. Suspended
# must mean should_suppress is False for every movement key (nothing
# withheld) AND nothing re-synthesized. These use the two real grabber
# classes; they are pure state, the OS hook that consults them is not here.

def _non_exclusive_grabbers():
    from utils.macos_movement_grabber import MacOSMovementKeyGrabber
    from utils.win32_movement_grabber import Win32MovementKeyGrabber
    return [Win32MovementKeyGrabber, MacOSMovementKeyGrabber]


@pytest.fixture(params=_non_exclusive_grabbers(), ids=["win32", "macos"])
def hooked(stage, request):
    grabber = request.param()
    assert grabber.needs_focused_passthrough is False
    # What prepare() does, minus its platform check.
    grabber._should_consume = stage.input._should_consume_grabbed_key
    grabber._on_grabs_changed = stage.input._on_grabs_changed
    stage.input._key_grabber = grabber
    stage.movement = sorted(stage.keymaps.get_keys_for_game("ttr"))
    assert stage.movement
    return stage


def suppressed(rig):
    return [key for key in rig.movement if rig.input._suppress_predicate(key)]


def test_hook_baseline_withholds_the_bound_keys_and_redelivers(hooked):
    focus(hooked, "a")
    assert suppressed(hooked) == hooked.movement
    assert hooked.input._strict_ttr_active() is True
    assert {win for _action, win, _key in press_forward(hooked)} == {"a", "b"}


def test_hook_withholds_nothing_while_stopped(hooked):
    focus(hooked, "a")
    hooked.session.stop()
    assert suppressed(hooked) == []
    assert hooked.input._key_grabber._grabbed_keysyms is None
    assert hooked.input._strict_ttr_active() is False
    assert press_forward(hooked) == []


def test_hook_stays_off_across_focus_changes_while_stopped(hooked):
    hooked.session.stop()
    for window_id in ("a", "b", "", "b"):
        focus(hooked, window_id)
        assert suppressed(hooked) == []
        assert press_forward(hooked) == []


def test_hook_is_restored_on_start(hooked):
    focus(hooked, "a")
    hooked.session.stop()
    focus(hooked, "b")
    hooked.session.start()
    assert suppressed(hooked) == hooked.movement
    assert {win for _action, win, _key in press_forward(hooked)} == {"a", "b"}


def test_the_consume_predicate_says_no_from_the_moment_routing_is_suspended(hooked):
    """A grabber that takes its grabs down a moment later on its own thread
    (X11) asks this per event in between; it must already say no."""
    focus(hooked, "a")
    key = hooked.movement[0]
    assert hooked.input._should_consume_grabbed_key(key) is True
    hooked.input._routing_suspended = True          # grabs not yet removed
    assert hooked.input._should_consume_grabbed_key(key) is False
    assert suppressed(hooked) == []
