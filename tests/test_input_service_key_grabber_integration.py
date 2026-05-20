"""Tests for InputService's wiring of the X11 movement grabber:
the should_consume callback and the lifecycle hooks."""

import queue
from unittest.mock import MagicMock

import pytest

from services import input_service
from services.input_service import (
    InputService,
    _passthrough_keysyms_for_canonical,
)


@pytest.fixture
def svc(monkeypatch):
    wm = MagicMock()
    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
    )
    return s


def test_should_consume_false_when_chat_active(svc):
    svc.global_chat_active = True
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_false_when_no_active_window(svc):
    svc.window_manager.get_active_window.return_value = None
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_true_when_active_window_is_cc(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)
    assert svc._should_consume_grabbed_key("Up") is True


def test_should_consume_false_when_active_window_is_ttr(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)
    assert svc._should_consume_grabbed_key("Up") is False


def test_should_consume_false_when_registry_lookup_raises(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: (_ for _ in ()).throw(RuntimeError("registry borked")))
    assert svc._should_consume_grabbed_key("Up") is False


def test_on_grabbed_key_enqueues_into_event_queue(svc):
    q = queue.Queue()
    svc.get_event_queue = lambda: q
    svc._on_grabbed_key("keydown", "Up")
    svc._on_grabbed_key("keyup", "Up")
    assert q.get_nowait() == ("keydown", "Up")
    assert q.get_nowait() == ("keyup", "Up")


def test_on_grabbed_key_swallows_full_queue(svc, capsys):
    full_q = queue.Queue(maxsize=1)
    full_q.put_nowait(("keydown", "X"))  # fill it
    svc.get_event_queue = lambda: full_q
    # Must not raise; the print falls into capsys.
    svc._on_grabbed_key("keydown", "Up")


def test_start_key_grabber_skipped_when_xlib_unavailable(svc, monkeypatch):
    """If python-xlib isn't available, the grabber attribute stays None
    and start_key_grabber returns silently."""
    import utils.x11_movement_grabber as gm
    monkeypatch.setattr(gm, "xlib_available", lambda: False)
    svc._start_key_grabber()
    assert svc._key_grabber is None


def test_start_key_grabber_skipped_when_grabber_prepare_returns_false(svc, monkeypatch):
    """Grabber instantiated but prepare() fails (e.g. cannot open display);
    InputService clears the attribute."""
    import utils.x11_movement_grabber as gm
    monkeypatch.setattr(gm, "xlib_available", lambda: True)
    monkeypatch.setattr("services.wine_runtimes.discover_cc_installs", lambda: ["fake-install"])

    class FakeGrabber:
        def prepare(self, **_):
            return False
        def stop(self):
            pass
    monkeypatch.setattr(gm, "MovementKeyGrabber", FakeGrabber)

    svc._start_key_grabber()
    assert svc._key_grabber is None


def test_shutdown_calls_grabber_stop(svc, monkeypatch):
    fake = MagicMock()
    svc._key_grabber = fake
    monkeypatch.setattr(input_service, "wine_input_bridge", MagicMock(), raising=False)
    svc.shutdown()
    fake.stop.assert_called_once()
    assert svc._key_grabber is None


def test_passthrough_keysyms_for_wasd_canonical_includes_movement_modifiers_letters():
    keys = _passthrough_keysyms_for_canonical("wasd")
    # Canonical movement keys
    assert "w" in keys and "a" in keys and "s" in keys and "d" in keys
    # Modifiers
    assert "Shift_L" in keys and "Control_L" in keys and "Alt_L" in keys
    # Common action keys
    assert "space" in keys and "Tab" in keys and "Escape" in keys
    # Common letters used in CC bindings (q=gags, e=tasks)
    assert "q" in keys and "e" in keys
    # Digits
    assert "1" in keys and "9" in keys


def test_passthrough_keysyms_for_arrows_canonical_includes_arrows():
    keys = _passthrough_keysyms_for_canonical("arrows")
    assert "Up" in keys and "Down" in keys and "Left" in keys and "Right" in keys


def test_on_passthrough_key_no_active_window_is_a_noop(svc):
    svc.window_manager.get_active_window.return_value = None
    # Must not raise even though no bridge call will succeed.
    svc._on_passthrough_key("keydown", "w")


def test_on_passthrough_key_non_cc_window_is_a_noop(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    bridge = MagicMock()
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", bridge)

    svc._on_passthrough_key("keydown", "w")

    bridge.assert_not_called()


def test_on_passthrough_key_cc_window_routes_to_wine_bridge(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    svc.window_manager.get_window_ids.return_value = ["w1", "w2"]
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    bridge = MagicMock()
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", bridge)

    svc._on_passthrough_key("keydown", "w")

    bridge.assert_called_once_with("w1", ["w1", "w2"], "keydown", "w")


def test_on_passthrough_key_swallows_bridge_exceptions(svc, monkeypatch):
    svc.window_manager.get_active_window.return_value = "w1"
    svc.window_manager.get_window_ids.return_value = ["w1"]
    from utils import game_registry as gr
    fake_reg = MagicMock()
    fake_reg.get_game_for_window.return_value = "cc"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    def boom(*_args, **_kw):
        raise RuntimeError("bridge unavailable")
    monkeypatch.setattr("utils.wine_input_bridge.send_to_window", boom)

    # Must not raise.
    svc._on_passthrough_key("keydown", "w")


def test_start_key_grabber_skips_when_no_cc_installs(monkeypatch, svc):
    """When discover_cc_installs() returns empty, the grabber is never
    instantiated. TTMT opens zero Xlib connections for grab purposes."""
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs", lambda: []
    )
    fake_grabber_cls = MagicMock()
    monkeypatch.setattr(
        "utils.x11_movement_grabber.MovementKeyGrabber", fake_grabber_cls
    )
    svc._start_key_grabber()
    assert svc._key_grabber is None
    assert fake_grabber_cls.call_count == 0


def test_start_key_grabber_instantiates_when_cc_installs_present(monkeypatch, svc):
    """When CC is detected on disk, the grabber is instantiated and
    prepare() is called."""
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs", lambda: ["fake-install"]
    )
    fake_instance = MagicMock()
    fake_instance.prepare.return_value = True
    fake_grabber_cls = MagicMock(return_value=fake_instance)
    monkeypatch.setattr(
        "utils.x11_movement_grabber.MovementKeyGrabber", fake_grabber_cls
    )
    monkeypatch.setattr(
        "utils.x11_movement_grabber.xlib_available", lambda: True
    )
    svc._start_key_grabber()
    assert svc._key_grabber is fake_instance
    fake_instance.prepare.assert_called_once()
    # install_grabs() is no longer called unconditionally at startup;
    # focus-aware behavior is covered by the lifecycle tests below.


def test_start_key_grabber_is_idempotent(monkeypatch):
    """stop()+start() flows (main.py input-backend change, tab window
    reassignment) call _start_key_grabber twice. Second call must be a
    no-op: no second MovementKeyGrabber instance, no second signal
    connect."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"200": "cc"},
        assignments=[0],
    )
    svc._start_key_grabber()
    first_instance = svc._key_grabber
    first_connect_count = svc.window_manager.active_window_changed.connect.call_count
    svc._start_key_grabber()
    # Same grabber instance; no new connect.
    assert svc._key_grabber is first_instance
    assert svc.window_manager.active_window_changed.connect.call_count == first_connect_count


def _make_focused_svc(monkeypatch, focus_window_id, registry_mapping, assignments):
    """Helper: build an InputService whose WindowManager reports the
    given focused window and whose GameRegistry returns the given games.
    Returns (svc, fake_grabber_instance).

    Tests using this helper must also call `svc._start_key_grabber()`
    explicitly to wire the slot; this helper only constructs.
    """
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs", lambda: ["fake-install"]
    )
    fake_instance = MagicMock()
    fake_instance.prepare.return_value = True
    fake_grabber_cls = MagicMock(return_value=fake_instance)
    monkeypatch.setattr(
        "utils.x11_movement_grabber.MovementKeyGrabber", fake_grabber_cls
    )
    monkeypatch.setattr(
        "utils.x11_movement_grabber.xlib_available", lambda: True
    )

    fake_registry = MagicMock()
    fake_registry.get_game_for_window.side_effect = lambda wid: registry_mapping.get(str(wid))
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )

    wm = MagicMock()
    wm.get_active_window.return_value = focus_window_id
    wm.get_window_ids.return_value = list(registry_mapping.keys())

    fake_km = MagicMock()
    # Set 0 forward=w (WASD); Set 1 forward=Up (arrows). Used by
    # _canonical_set_for_toon_index to decide which keyset to suppress.
    def get_key_for_action(game, set_idx, action):
        if action != "forward":
            return None
        return "w" if set_idx == 0 else "Up"
    fake_km.get_key_for_action.side_effect = get_key_for_action

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(registry_mapping),
        get_movement_modes=lambda: ["both"] * len(registry_mapping),
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: assignments,
        keymap_manager=fake_km,
    )
    return svc, fake_instance


def test_no_install_when_no_cc_window_focused(monkeypatch):
    """At startup, if a TTR window is focused, install_grabs is not called."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="100",
        registry_mapping={"100": "ttr", "200": "cc"},
        assignments=[0, 0],
    )
    svc._start_key_grabber()
    grabber.install_grabs.assert_not_called()


def test_install_wasd_canonical_when_wasd_cc_focused(monkeypatch):
    """CC window on WASD set (set_idx=0) is focused -> install_grabs('wasd')."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"100": "ttr", "200": "cc"},
        assignments=[0, 0],
    )
    svc._start_key_grabber()
    args, kwargs = grabber.install_grabs.call_args
    canonical = kwargs.get("canonical_set", args[0] if args else None)
    assert canonical == "wasd"


def test_install_arrows_canonical_when_arrows_cc_focused(monkeypatch):
    """CC window on arrows set (set_idx=1) is focused -> install_grabs('arrows')."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"100": "ttr", "200": "cc"},
        assignments=[0, 1],
    )
    svc._start_key_grabber()
    args, kwargs = grabber.install_grabs.call_args
    canonical = kwargs.get("canonical_set", args[0] if args else None)
    assert canonical == "arrows"


def test_focus_change_to_non_cc_uninstalls(monkeypatch):
    """Focus moves from CC to TTR -> uninstall_grabs called."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"100": "ttr", "200": "cc"},
        assignments=[0, 0],
    )
    svc._start_key_grabber()
    grabber.install_grabs.reset_mock()
    grabber.uninstall_grabs.reset_mock()
    svc.window_manager.get_active_window.return_value = "100"
    svc._on_active_window_changed_for_grabber("100")
    grabber.uninstall_grabs.assert_called_once()
    grabber.install_grabs.assert_not_called()


def test_focus_change_between_different_set_cc_swaps_canonical(monkeypatch):
    """Focus moves from CC-WASD to CC-arrows -> install with new canonical."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"200": "cc", "201": "cc"},
        assignments=[0, 1],
    )
    svc._start_key_grabber()
    grabber.install_grabs.reset_mock()
    svc.window_manager.get_active_window.return_value = "201"
    svc._on_active_window_changed_for_grabber("201")
    args, kwargs = grabber.install_grabs.call_args
    canonical = kwargs.get("canonical_set", args[0] if args else None)
    assert canonical == "arrows"


def test_focus_change_to_empty_window_id_uninstalls(monkeypatch):
    """Defensive: empty active_window_changed payload -> uninstall, no crash."""
    svc, grabber = _make_focused_svc(
        monkeypatch,
        focus_window_id="200",
        registry_mapping={"200": "cc"},
        assignments=[0],
    )
    svc._start_key_grabber()
    grabber.uninstall_grabs.reset_mock()
    svc._on_active_window_changed_for_grabber("")
    grabber.uninstall_grabs.assert_called_once()
