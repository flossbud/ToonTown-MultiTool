from utils import wine_input_bridge


class _FakeBridge:
    def __init__(self):
        self.calls = []

    def send(self, op, index, keysym, active_index=-1):
        self.calls.append((op, index, keysym, active_index))
        return True

    def cross_check_sort_order(self, window_ids):
        return True


def test_send_to_window_passes_target_and_active_indices(monkeypatch):
    bridge = _FakeBridge()
    monkeypatch.setattr(wine_input_bridge.x11_discovery, "get_window_pid", lambda wid: 123)
    monkeypatch.setattr(wine_input_bridge.x11_discovery, "get_active_window_id", lambda: "win-1")
    monkeypatch.setattr(wine_input_bridge, "_bridge_for_pid", lambda pid: bridge)

    ok = wine_input_bridge.send_to_window(
        "win-2",
        ["win-1", "win-2"],
        "keydown",
        "w",
    )

    assert ok is True
    assert bridge.calls == [("down", 1, "w", 0)]


def test_send_to_window_tap_wraps_modifiers(monkeypatch):
    bridge = _FakeBridge()
    monkeypatch.setattr(wine_input_bridge.x11_discovery, "get_window_pid", lambda wid: 123)
    monkeypatch.setattr(wine_input_bridge.x11_discovery, "get_active_window_id", lambda: "win-2")
    monkeypatch.setattr(wine_input_bridge, "_bridge_for_pid", lambda pid: bridge)

    ok = wine_input_bridge.send_to_window(
        "win-1",
        ["win-1", "win-2"],
        "key",
        "q",
        modifiers=["shift"],
    )

    assert ok is True
    assert bridge.calls == [
        ("down", 0, "Shift_L", 1),
        ("tap", 0, "q", 1),
        ("up", 0, "Shift_L", 1),
    ]


def test_send_to_window_returns_false_without_pid(monkeypatch):
    monkeypatch.setattr(wine_input_bridge.x11_discovery, "get_window_pid", lambda wid: None)

    assert wine_input_bridge.send_to_window("win-1", ["win-1"], "keydown", "w") is False


def test_input_service_uses_bridge_for_cc_before_xlib(monkeypatch):
    from services.input_service import InputService
    from utils.game_registry import GameRegistry

    class _WindowManager:
        def get_window_ids(self):
            return ["cc-1", "cc-2"]

        def get_active_window(self):
            return "cc-1"

        def assign_windows(self):
            raise AssertionError("fallback backend should not run")

    class _Xlib:
        def send_keydown(self, *args):
            raise AssertionError("xlib should not be used when bridge succeeds")

    calls = []
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window", lambda wid: "cc")
    monkeypatch.setattr(
        wine_input_bridge,
        "send_to_window",
        lambda win_id, window_ids, action, keysym, modifiers=None: calls.append(
            (win_id, window_ids, action, keysym, modifiers)
        ) or True,
    )

    svc = InputService(
        window_manager=_WindowManager(),
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["WASD", "WASD"],
        get_event_queue_func=lambda: None,
    )
    svc._xlib = _Xlib()

    svc._send_via_backend("keydown", "cc-2", "w")

    assert calls == [("cc-2", ["cc-1", "cc-2"], "keydown", "w", None)]


def test_shutdown_all_clears_bridges_and_calls_shutdown(monkeypatch):
    from utils import wine_input_bridge as wib

    class FakeBridge:
        def __init__(self):
            self.shutdown_called = False
        def shutdown(self):
            self.shutdown_called = True

    a, b = FakeBridge(), FakeBridge()
    wib._BRIDGES["/prefix/a"] = a
    wib._BRIDGES["/prefix/b"] = b
    try:
        wib.shutdown_all()
        assert a.shutdown_called and b.shutdown_called
        assert wib._BRIDGES == {}
    finally:
        wib._BRIDGES.clear()


def test_send_to_window_handles_last_window_as_active(monkeypatch):
    """Regression guard for review item I-2: when the active window is the
    last sorted index, the Python side sends activeIndex == len(windows)-1.
    The bridge must accept this without erroring. (The original review
    flagged a perceived off-by-one in the C# helper's foreground-reorder
    logic; verification showed List<T>.Insert(Count, item) is legal in
    C# and equivalent to Add, so the C# code is correct as-is. This test
    pins the Python-side contract so a future refactor doesn't break it.)"""
    from utils import wine_input_bridge
    from utils.game_registry import GameRegistry

    captured = []

    class StubBridge:
        def send(self, op, index, keysym, active_index):
            captured.append((op, index, keysym, active_index))
            return True

        def cross_check_sort_order(self, window_ids):
            return True

    monkeypatch.setattr(wine_input_bridge, "_bridge_for_pid", lambda _pid: StubBridge())
    monkeypatch.setattr(
        GameRegistry,
        "_get_host_pid_for_window_xres",
        staticmethod(lambda _wid: 12345),
    )
    monkeypatch.setattr(
        wine_input_bridge.x11_discovery,
        "get_active_window_id",
        lambda: "win_c",  # active is the last window in the list
    )

    ok = wine_input_bridge.send_to_window(
        "win_c",
        ["win_a", "win_b", "win_c"],
        "keydown",
        "w",
    )
    assert ok
    assert captured == [("down", 2, "w", 2)]


def test_input_service_falls_through_to_xlib_for_ttr(monkeypatch):
    """Regression guard for review item I-4: the Wine bridge must only be
    invoked for game='cc' windows. TTR (native Linux) must continue to use
    the Xlib backend even when the bridge module is importable."""
    import sys
    monkeypatch.setattr(sys, "platform", "linux")

    from utils.game_registry import GameRegistry
    monkeypatch.setattr(
        GameRegistry,
        "instance",
        classmethod(lambda cls: type("GR", (), {
            "get_game_for_window": staticmethod(lambda _wid: "ttr"),
        })()),
    )

    bridge_calls = []
    xlib_calls = []

    def stub_send_to_window(*args, **kwargs):
        bridge_calls.append((args, kwargs))
        return True  # if reached, would block Xlib — but it must NOT be reached

    from utils import wine_input_bridge
    monkeypatch.setattr(wine_input_bridge, "send_to_window", stub_send_to_window)

    class StubXlib:
        def send_keydown(self, win_id, keysym, state=0):
            xlib_calls.append(("keydown", win_id, keysym))
            return True
        def send_keyup(self, win_id, keysym, state=0):
            xlib_calls.append(("keyup", win_id, keysym))
            return True
        def send_key(self, win_id, keysym, modifiers=None):
            xlib_calls.append(("key", win_id, keysym, modifiers))
            return True

    # Build a minimal InputService instance via __new__ (avoid full __init__).
    from services.input_service import InputService
    svc = InputService.__new__(InputService)
    svc._xlib = StubXlib()
    svc.window_manager = type("WM", (), {"get_window_ids": staticmethod(lambda: ["win_a"])})()
    svc.logging_enabled = False
    svc.input_log = type("Sig", (), {"emit": staticmethod(lambda *_a, **_k: None)})()

    svc._send_via_backend("keydown", "win_a", "w")
    assert bridge_calls == [], "Wine bridge must not be called for TTR windows"
    assert xlib_calls == [("keydown", "win_a", "w")], "Xlib backend must be called for TTR"


def test_bad_prefix_cooldown_allows_retry_after_expiry(monkeypatch):
    """Regression guard for review item I-5: a prefix that recently failed
    to set up a bridge should be retried after the cooldown expires."""
    from utils import wine_input_bridge as wib

    fake_now = [1000.0]
    monkeypatch.setattr(wib.time, "monotonic", lambda: fake_now[0])

    # Seed an "old" failure (expired) and a "fresh" failure (still cooling)
    wib._BAD_PREFIXES.clear()
    wib._BAD_PREFIXES["/prefix/old"] = fake_now[0] - (wib._BAD_PREFIX_COOLDOWN + 1)
    wib._BAD_PREFIXES["/prefix/fresh"] = fake_now[0] - 1.0

    try:
        # Old entry: cooldown has expired. _bridge_for_pid should
        # pop the entry and re-attempt setup. We patch the next gate
        # (_proton_dir_for_pid) so it falls through and re-adds the entry
        # with a new timestamp.
        monkeypatch.setattr(wib, "_read_process_env", lambda _pid: {"WINEPREFIX": "/prefix/old"})
        monkeypatch.setattr(wib, "_proton_dir_for_pid", lambda _pid, _env: None)
        result = wib._bridge_for_pid(99999)
        assert result is None
        # The old entry should be replaced with a fresh "now" timestamp.
        assert wib._BAD_PREFIXES["/prefix/old"] == fake_now[0]

        # Fresh entry: still within cooldown. Must short-circuit BEFORE
        # _proton_dir_for_pid is consulted.
        monkeypatch.setattr(wib, "_read_process_env", lambda _pid: {"WINEPREFIX": "/prefix/fresh"})
        proton_dir_calls = []
        monkeypatch.setattr(
            wib,
            "_proton_dir_for_pid",
            lambda _pid, _env: (proton_dir_calls.append(1) or None),
        )
        result = wib._bridge_for_pid(99999)
        assert result is None
        assert proton_dir_calls == [], "Fresh BAD_PREFIX entry must short-circuit before _proton_dir_for_pid"
    finally:
        wib._BAD_PREFIXES.clear()


def test_cross_check_sort_order_accepts_monotonic_helper_response(monkeypatch):
    """Regression guard for review item I-1: cross-check should accept a
    helper list with strictly increasing Left coordinates."""
    from utils.wine_input_bridge import WineInputBridge

    bridge = WineInputBridge.__new__(WineInputBridge)
    bridge.port = 12345
    bridge.prefix = "/prefix/test"
    monkeypatch.setattr(
        WineInputBridge, "_request",
        lambda self, line, timeout=0.5: "OK 1A:10:0,2B:800:0,3C:1600:0",
    )
    assert bridge.cross_check_sort_order(["win_a", "win_b", "win_c"]) is True


def test_cross_check_sort_order_rejects_count_mismatch(monkeypatch):
    """Cross-check must reject when the helper reports a different
    number of windows than the caller knows about."""
    from utils.wine_input_bridge import WineInputBridge

    bridge = WineInputBridge.__new__(WineInputBridge)
    bridge.port = 12345
    bridge.prefix = "/prefix/test"
    monkeypatch.setattr(
        WineInputBridge, "_request",
        lambda self, line, timeout=0.5: "OK 1A:10:0",  # only one entry
    )
    assert bridge.cross_check_sort_order(["win_a", "win_b"]) is False


def test_cross_check_sort_order_rejects_non_monotonic(monkeypatch):
    """Cross-check must reject when the helper's Left values are not
    monotonically non-decreasing (sort axes disagree)."""
    from utils.wine_input_bridge import WineInputBridge

    bridge = WineInputBridge.__new__(WineInputBridge)
    bridge.port = 12345
    bridge.prefix = "/prefix/test"
    monkeypatch.setattr(
        WineInputBridge, "_request",
        lambda self, line, timeout=0.5: "OK 1A:1600:0,2B:10:0",  # out of order
    )
    assert bridge.cross_check_sort_order(["win_a", "win_b"]) is False


def test_cross_check_sort_order_accepts_empty_when_no_windows(monkeypatch):
    """Empty helper response is valid IFF the caller also has no windows."""
    from utils.wine_input_bridge import WineInputBridge

    bridge = WineInputBridge.__new__(WineInputBridge)
    bridge.port = 12345
    bridge.prefix = "/prefix/test"
    monkeypatch.setattr(
        WineInputBridge, "_request",
        lambda self, line, timeout=0.5: "OK ",
    )
    assert bridge.cross_check_sort_order([]) is True
    assert bridge.cross_check_sort_order(["win_a"]) is False


def test_port_for_prefix_matches_bridge_instance_formula():
    """The module-level port helper must agree with what
    WineInputBridge.__init__ computes for the same prefix, otherwise the
    pre-launch sweep targets a port the running helper isn't bound to."""
    from utils.wine_input_bridge import WineInputBridge, _port_for_prefix

    prefix = "/home/u/.local/share/Steam/steamapps/compatdata/3555655912/pfx"
    bridge = WineInputBridge.__new__(WineInputBridge)
    bridge.__init__(prefix=prefix, proton_dir="/opt/proton", env={})

    assert _port_for_prefix(prefix) == bridge.port


def test_shutdown_for_prefix_calls_in_memory_bridge_shutdown(monkeypatch):
    """When a WineInputBridge instance is in _BRIDGES for the given
    prefix, shutdown_for_prefix must pop it and call .shutdown() on it
    (reaping the Popen handle), not fall through to the TCP path."""
    from utils import wine_input_bridge as wib

    class FakeBridge:
        def __init__(self):
            self.shutdown_called = False
        def shutdown(self):
            self.shutdown_called = True

    quits = []
    monkeypatch.setattr(wib, "_send_quit", lambda port: quits.append(port))

    prefix = "/prefix/a"
    fake = FakeBridge()
    wib._BRIDGES[prefix] = fake
    try:
        wib.shutdown_for_prefix(prefix)
        assert fake.shutdown_called is True
        assert prefix not in wib._BRIDGES
        assert quits == [], "TCP fallback must not fire when in-memory bridge was found"
    finally:
        wib._BRIDGES.pop(prefix, None)


def test_shutdown_for_prefix_falls_back_to_tcp_quit_when_no_in_memory_bridge(monkeypatch):
    """If a previous TTMT session crashed, its WineInputBridge instance
    is gone but TTMTWineInputBridge.exe may still be alive inside the
    Wine prefix, listening on the deterministic port. shutdown_for_prefix
    must send a TCP quit to that port in this case."""
    from utils import wine_input_bridge as wib

    quits = []
    monkeypatch.setattr(wib, "_send_quit", lambda port: quits.append(port))

    prefix = "/prefix/orphan"
    wib._BRIDGES.pop(prefix, None)
    wib.shutdown_for_prefix(prefix)
    assert quits == [wib._port_for_prefix(prefix)]


def test_shutdown_for_prefix_normalizes_path_to_match_bridges_key(monkeypatch, tmp_path):
    """_BRIDGES is keyed by os.path.realpath(prefix). Callers may pass
    a path with a trailing slash or a non-realpath form;
    shutdown_for_prefix must normalize before lookup or it'll miss the
    in-memory bridge and incorrectly fall through to the TCP path."""
    from utils import wine_input_bridge as wib
    import os

    real = tmp_path / "pfx"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)

    canonical = os.path.realpath(str(real))

    class FakeBridge:
        def __init__(self):
            self.shutdown_called = False
        def shutdown(self):
            self.shutdown_called = True

    fake = FakeBridge()
    wib._BRIDGES[canonical] = fake
    quits = []
    monkeypatch.setattr(wib, "_send_quit", lambda port: quits.append(port))
    try:
        wib.shutdown_for_prefix(str(link) + "/")
        assert fake.shutdown_called is True
        assert canonical not in wib._BRIDGES
        assert quits == []
    finally:
        wib._BRIDGES.pop(canonical, None)
