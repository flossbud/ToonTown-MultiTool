"""Win32MouseCapture unit tests, cross-platform via an injected fake
listener factory (production default lazily builds pynput's Listener)."""
import pytest

from utils.win32_mouse_capture import Win32MouseCapture, mask_for


class FakeListener:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class PynputLikeListener:
    """Mimics real pynput: `running` set on start and NEVER cleared on
    thread death; liveness only visible via is_alive()."""

    def __init__(self):
        self.running = False
        self._alive = False

    def start(self):
        self.running = True
        self._alive = True

    def stop(self):
        self.running = False
        self._alive = False

    def is_alive(self):
        return self._alive

    def die_silently(self):
        self._alive = False  # thread died; `running` stays True


class FakeButton:
    def __init__(self, name):
        self.name = name


LEFT, RIGHT, X1 = FakeButton("left"), FakeButton("right"), FakeButton("x1")


@pytest.fixture
def cap():
    events = []
    hooks = {}

    def factory(on_move, on_click):
        hooks["move"], hooks["click"] = on_move, on_click
        return FakeListener()

    c = Win32MouseCapture(
        lambda *e: events.append(e), listener_factory=factory)
    assert c.start() is True
    yield c, events, hooks
    c.stop()


def test_mask_for_x_button_masks():
    assert mask_for(set()) == 0
    assert mask_for({1}) == 0x100
    assert mask_for({1, 3}) == 0x100 | 0x400


def test_motion_emitted_with_current_mask(cap):
    c, events, hooks = cap
    hooks["move"](100.7, 200.2)
    kind, x, y, state, t = events[0]
    assert (kind, x, y, state) == ("motion", 100, 200, 0)
    assert isinstance(t, int)


def test_press_excludes_own_button_release_includes_it(cap):
    c, events, hooks = cap
    hooks["click"](10, 10, LEFT, True)
    hooks["move"](11, 10)
    hooks["click"](12, 10, LEFT, False)
    kinds = [e[0] for e in events]
    assert kinds == ["press", "motion", "release"]
    assert events[0][3] == 0       # press: mask BEFORE the button went down
    assert events[1][3] == 0x100   # held during the drag
    assert events[2][3] == 0x100   # release: still includes button 1


def test_non_left_buttons_update_mask_only(cap):
    c, events, hooks = cap
    hooks["click"](5, 5, RIGHT, True)
    assert events == []            # no press event for button 3
    hooks["move"](6, 5)
    assert events[0][3] == 0x400   # but motion carries Button3Mask
    hooks["click"](7, 5, RIGHT, False)
    assert len(events) == 1        # and no release event either


def test_unknown_button_ignored(cap):
    c, events, hooks = cap
    hooks["click"](5, 5, X1, True)
    hooks["move"](6, 5)
    assert events[0][3] == 0


def test_stop_is_idempotent_and_clears_running(cap):
    c, events, hooks = cap
    assert c.is_running() is True
    c.stop()
    c.stop()
    assert c.is_running() is False


def test_callback_exception_calls_on_died_once():
    died = []
    hooks = {}

    def factory(on_move, on_click):
        hooks["move"] = on_move
        return FakeListener()

    def exploding_handler(*e):
        raise RuntimeError("consumer bug")

    c = Win32MouseCapture(exploding_handler, on_died=lambda: died.append(1),
                          listener_factory=factory)
    c.start()
    hooks["move"](1, 1)
    hooks["move"](2, 2)
    assert died == [1]
    assert c.is_running() is False


def test_failed_listener_start_returns_false():
    def factory(on_move, on_click):
        raise OSError("no hook for you")

    c = Win32MouseCapture(lambda *e: None, listener_factory=factory)
    assert c.start() is False
    assert c.is_running() is False


def test_dead_hook_thread_reports_not_running():
    listeners = []

    def factory(on_move, on_click):
        l = PynputLikeListener()
        listeners.append(l)
        return l

    c = Win32MouseCapture(lambda *e: None, listener_factory=factory)
    assert c.start() is True
    assert c.is_running() is True
    listeners[0].die_silently()        # hook died; pynput keeps running=True
    assert c.is_running() is False     # is_alive() exposes the death
    c.stop()


def test_startup_window_running_false_is_not_death():
    class SlowStartListener(PynputLikeListener):
        def start(self):
            self._alive = True         # thread spawned...
            self.running = False       # ...but run() not yet executing

    c = Win32MouseCapture(
        lambda *e: None, listener_factory=lambda m, k: SlowStartListener())
    assert c.start() is True
    assert c.is_running() is True      # liveness, not pynput's flag
    c.stop()


def test_no_emission_after_stop():
    events = []
    hooks = {}

    def factory(on_move, on_click):
        hooks["move"], hooks["click"] = on_move, on_click
        return FakeListener()

    c = Win32MouseCapture(lambda *e: events.append(e),
                          listener_factory=factory)
    c.start()
    c.stop()
    hooks["move"](1, 1)                          # post-stop straggler
    hooks["click"](1, 1, LEFT, True)
    assert events == []


def test_release_without_seen_press_still_carries_button_mask(cap):
    c, events, hooks = cap
    hooks["click"](9, 9, LEFT, False)  # release with no prior press
    assert events == [("release", 9, 9, 0x100, events[0][4])]


def test_start_is_idempotent_single_factory_call():
    built = []

    def factory(on_move, on_click):
        built.append(1)
        return FakeListener()

    c = Win32MouseCapture(lambda *e: None, listener_factory=factory)
    assert c.start() is True
    assert c.start() is True
    assert built == [1]
    c.stop()
