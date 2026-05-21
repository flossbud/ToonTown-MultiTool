"""Tests for WineConsoleHider's polling lifecycle, gating, and matching."""

import pytest


class _FakeTimer:
    """Minimal QTimer stand-in. Records start/stop, lets tests drive ticks."""
    def __init__(self):
        self.interval = None
        self.started = False
        self.stopped = False
        self._cb = None

    def setInterval(self, ms):
        self.interval = ms

    def timeout_connect(self, cb):
        self._cb = cb

    def start(self):
        self.started = True
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.started = False

    def isActive(self):
        return self.started and not self.stopped

    def fire(self):
        """Drive one tick. Idempotent if stopped."""
        if self.started and not self.stopped and self._cb is not None:
            self._cb()


class _Recorder:
    def __init__(self, windows=None):
        # windows is a list-of-lists: tick N (0-indexed) sees windows[N].
        self.windows = windows or []
        self.tick_index = 0
        self.unmapped = []

    def enumerate(self):
        if self.tick_index < len(self.windows):
            tick_windows = self.windows[self.tick_index]
        else:
            tick_windows = []
        self.tick_index += 1
        return list(tick_windows)

    def unmap(self, wid):
        self.unmapped.append(wid)


class _SettingsStub:
    def __init__(self, value=True):
        self._value = value

    def get(self, key, default=None):
        return self._value


def _make_hider(*, setting=True, windows=None):
    """Build a hider wired to fakes. Returns (hider, recorder, fake_timer)."""
    from services.wine_console_hider import WineConsoleHider
    rec = _Recorder(windows=windows or [])
    timer = _FakeTimer()
    hider = WineConsoleHider(
        _SettingsStub(setting),
        enumerator=rec.enumerate,
        unmapper=rec.unmap,
        timer_factory=lambda: timer,
    )
    return hider, rec, timer


def test_setting_off_means_no_timer_no_enumeration():
    hider, rec, timer = _make_hider(setting=False, windows=[
        [(0x100, r"C:\foo\CorporateClash.exe")],
    ])
    hider.on_game_launched(pid=1234)
    assert timer.started is False
    assert rec.tick_index == 0  # enumerator never called
    assert rec.unmapped == []


def test_setting_on_starts_timer_with_expected_interval():
    from services.wine_console_hider import WATCH_INTERVAL_MS
    hider, _rec, timer = _make_hider(setting=True, windows=[])
    hider.on_game_launched(pid=1234)
    assert timer.started is True
    assert timer.interval == WATCH_INTERVAL_MS


def test_tick_unmaps_matching_window_and_keeps_running():
    """Match on tick 1; timer keeps running (in case more consoles appear),
    but the same wid is not re-unmapped."""
    hider, rec, timer = _make_hider(setting=True, windows=[
        [],  # tick 0: nothing
        [(0x100, r"C:\foo\CorporateClash.exe")],  # tick 1: match
        [(0x100, r"C:\foo\CorporateClash.exe")],  # tick 2: same wid again (should not re-unmap)
    ])
    hider.on_game_launched(pid=1234)
    timer.fire()  # tick 0
    assert rec.unmapped == []
    timer.fire()  # tick 1
    assert rec.unmapped == [0x100]
    timer.fire()  # tick 2
    assert rec.unmapped == [0x100]  # NOT [0x100, 0x100]
    # Timer is still active (it stops only on timeout, not on first hide).
    assert timer.isActive()


def test_tick_unmaps_multiple_matching_windows_in_same_tick():
    """Multi-account launch: two consoles appear in the same tick."""
    hider, rec, timer = _make_hider(setting=True, windows=[
        [
            (0x100, r"C:\foo\CorporateClash.exe"),
            (0x200, r"C:\bar\CorporateClash.exe"),
            (0x300, "Firefox"),  # decoy: should not be unmapped
        ],
    ])
    hider.on_game_launched(pid=1234)
    timer.fire()
    assert sorted(rec.unmapped) == [0x100, 0x200]


def test_tick_skips_non_matching_windows():
    hider, rec, timer = _make_hider(setting=True, windows=[
        [
            (0x100, "Corporate Clash [1.11.17777]"),  # game window, NOT console
            (0x200, "Firefox"),
        ],
    ])
    hider.on_game_launched(pid=1234)
    timer.fire()
    assert rec.unmapped == []


def test_timer_stops_after_max_ticks():
    """75 ticks at 200ms = 15s. After tick 75, timer must be stopped."""
    from services.wine_console_hider import WATCH_DURATION_MS, WATCH_INTERVAL_MS
    expected_ticks = WATCH_DURATION_MS // WATCH_INTERVAL_MS
    hider, _rec, timer = _make_hider(setting=True, windows=[])
    hider.on_game_launched(pid=1234)
    for _ in range(expected_ticks):
        assert timer.isActive()
        timer.fire()
    assert timer.isActive() is False


def test_relaunch_resets_tick_counter_and_already_unmapped_set():
    """Multi-account: first launch hides a console on tick 0, then a SECOND
    launch fires. The new launch should re-enter watching from tick 0 and a
    new console with the same wid (recycled) is unmappable again."""
    hider, rec, timer = _make_hider(setting=True, windows=[
        [(0x100, r"C:\foo\CorporateClash.exe")],  # launch 1 tick 0
        [(0x100, r"C:\foo\CorporateClash.exe")],  # launch 2 tick 0 (wid recycled)
    ])
    hider.on_game_launched(pid=1)
    timer.fire()
    assert rec.unmapped == [0x100]
    hider.on_game_launched(pid=2)  # restart watch
    timer.fire()
    assert rec.unmapped == [0x100, 0x100]


def test_enumerator_exception_is_swallowed():
    """A bad tick must not stop the timer. python-Xlib calls can intermittently
    fail under heavy load."""
    def boom():
        raise RuntimeError("simulated X11 hiccup")
    from services.wine_console_hider import WineConsoleHider
    timer = _FakeTimer()
    hider = WineConsoleHider(
        _SettingsStub(True),
        enumerator=boom,
        unmapper=lambda wid: None,
        timer_factory=lambda: timer,
    )
    hider.on_game_launched(pid=1)
    # The hider must not raise.
    timer.fire()
    assert timer.isActive() is True


def test_unmapper_exception_is_swallowed():
    """A failed unmap must not stop the timer or prevent later attempts."""
    from services.wine_console_hider import WineConsoleHider

    rec_unmapped = []
    def bad_unmap(wid):
        rec_unmapped.append(wid)
        raise RuntimeError("simulated unmap failure")

    windows_per_tick = [
        [(0x100, r"C:\foo\CorporateClash.exe")],
        [(0x200, r"C:\bar\CorporateClash.exe")],
    ]
    state = {"i": 0}
    def enumerate_():
        i = state["i"]
        state["i"] += 1
        return list(windows_per_tick[i]) if i < len(windows_per_tick) else []

    timer = _FakeTimer()
    hider = WineConsoleHider(
        _SettingsStub(True),
        enumerator=enumerate_,
        unmapper=bad_unmap,
        timer_factory=lambda: timer,
    )
    hider.on_game_launched(pid=1)
    timer.fire()  # tick 0: 0x100 raises
    timer.fire()  # tick 1: 0x200 raises
    assert rec_unmapped == [0x100, 0x200]
    assert timer.isActive() is True
