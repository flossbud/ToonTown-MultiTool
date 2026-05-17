from utils import wine_input_bridge


class _FakeBridge:
    def __init__(self):
        self.calls = []

    def send(self, op, index, keysym, active_index=-1):
        self.calls.append((op, index, keysym, active_index))
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
