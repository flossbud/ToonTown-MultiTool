"""Integration tests for the chat gate FSM inside InputService (TTMT_CHAT_FSM=1).

Covers the seams the pure-module suite (test_chat_fsm.py) cannot: the
dispatcher branch, capture-entry drain ordering, mirror-open/scoped-close
via bg_chat_open, the cleanup orphan guard, the keep-alive gate, chord
terminality, and the startup stamp. The flag is set BEFORE service
construction (it is read in __init__).

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_chat_fsm_integration.py -v
"""
from __future__ import annotations

import queue
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.chat_fsm import ChatState


def _build_service(monkeypatch, tmp_path, *, fsm=True, windows=None,
                   active="t1", games=None, enabled=None, chat_enabled=None):
    """FSM-mode InputService with stubbed transports, fresh tmp-dir keymap,
    and a recorded send list. No real grabber/backend/X work."""
    if fsm:
        monkeypatch.setenv("TTMT_CHAT_FSM", "1")
    else:
        # Default is ON since 2026-07-03: legacy needs the kill switch.
        monkeypatch.setenv("TTMT_CHAT_FSM", "0")
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        "services.input_service.InputService._start_key_grabber",
        lambda self: None,
    )
    monkeypatch.setattr(
        "services.input_service.InputService._apply_backend_setting",
        lambda self: None,
    )
    games = games or {}
    fake_registry = MagicMock()
    fake_registry.get_game_for_window.side_effect = (
        lambda wid: games.get(str(wid), "ttr")
    )
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry,
    )

    from utils.keymap_manager import KeymapManager
    from services.input_service import InputService

    windows = windows if windows is not None else ["t1", "t2"]
    wm = SimpleNamespace(
        get_active_window=lambda: active,
        get_window_ids=lambda: list(windows),
        assign_windows=lambda: None,
    )
    store = {}
    sm = SimpleNamespace(
        get=lambda k, d=None: store.get(k, d),
        set=lambda k, v: store.__setitem__(k, v),
        on_change=lambda cb: None,
    )
    eq: queue.Queue = queue.Queue()
    enabled = enabled if enabled is not None else [True, True]
    kwargs = {}
    if chat_enabled is not None:
        kwargs["get_chat_enabled"] = lambda: list(chat_enabled)
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: list(enabled),
        get_movement_modes=lambda: ["both"] * len(enabled),
        get_event_queue_func=lambda: eq,
        keymap_manager=KeymapManager(),
        get_keymap_assignments=lambda: [0] * len(enabled),
        settings_manager=sm,
        **kwargs,
    )
    sent = []
    svc._send_via_backend = lambda action, win, keysym, modifiers=None: sent.append(
        (action, str(win), keysym)
    )
    svc._resolve_keysym = lambda k: k
    return svc, eq, sent


def _args(svc):
    enabled = svc.get_enabled_toons()
    return (enabled, svc._get_assignments(enabled), svc._movement_keys(),
            svc.window_manager.get_window_ids())


# ── construction / flag plumbing ─────────────────────────────────────────────

class TestFlagPlumbing:
    def test_fsm_is_the_default(self, monkeypatch, tmp_path):
        """No env var at all -> FSM mode (default flipped 2026-07-03)."""
        svc, _, _ = _build_service(monkeypatch, tmp_path)  # fsm=True path
        monkeypatch.delenv("TTMT_CHAT_FSM", raising=False)
        from services.input_service import InputService
        import queue as _q
        bare = InputService(
            window_manager=svc.window_manager,
            get_enabled_toons=lambda: [True],
            get_movement_modes=lambda: ["both"],
            get_event_queue_func=lambda: _q.Queue(),
            settings_manager=None,
        )
        assert bare._fsm_enabled is True and bare._chat_fsm is not None

    def test_flag_off_no_fsm_plain_attrs(self, monkeypatch, tmp_path):
        svc, _, _ = _build_service(monkeypatch, tmp_path, fsm=False)
        assert svc._fsm_enabled is False and svc._chat_fsm is None
        svc.global_chat_active = True
        assert svc.global_chat_active is True
        svc._phantom_active = True
        assert svc._phantom_active is True
        svc.global_chat_active = False
        svc._phantom_active = False

    def test_flag_on_aliases_reflect_and_force_fsm(self, monkeypatch, tmp_path):
        svc, _, _ = _build_service(monkeypatch, tmp_path)
        assert svc._fsm_enabled is True
        svc.global_chat_active = True
        assert svc._chat_fsm.state is ChatState.CAPTURE
        assert svc.global_chat_active is True
        svc.global_chat_active = False
        assert svc._chat_fsm.state is ChatState.ROUTE
        svc._phantom_active = True
        assert svc._chat_fsm.state is ChatState.CAPTURE_SOFT
        assert svc._phantom_active is True
        assert svc.global_chat_active is False   # SOFT is not CAPTURE
        svc._phantom_active = False
        assert svc._chat_fsm.state is ChatState.ROUTE

    def test_consume_predicate_covers_soft_capture(self, monkeypatch, tmp_path):
        svc, _, _ = _build_service(monkeypatch, tmp_path,
                                   games={"t1": "cc", "t2": "cc"})
        assert svc._should_consume_grabbed_key("w") is True   # CC focused
        svc._phantom_active = True
        assert svc._should_consume_grabbed_key("w") is False  # gap closed


# ── dispatcher: chord flows ──────────────────────────────────────────────────

class TestChordFlows:
    def test_chord_open_drains_all_holds_then_captures(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path)
        enabled, assignments, mk, wids = _args(svc)
        now = time.monotonic()
        # Hold forward (TTR default set binds Up): bg toon gets keydown.
        svc._fsm_handle_keydown("Up", now, enabled, assignments, mk, wids)
        assert ("keydown", "t2", "Up") in sent
        sent.clear()
        # Enter with no typing context -> OPEN. Entry must DRAIN the hold.
        svc._fsm_handle_keydown("Return", now + 0.5, enabled, assignments, mk, wids)
        assert svc._chat_fsm.state is ChatState.CAPTURE
        assert ("keyup", "t2", "Up") in sent       # drained, not stuck walking
        assert len(svc.holds) == 0
        sent.clear()
        # Movement during capture routes nowhere.
        svc._fsm_handle_keydown("Left", now + 0.6, enabled, assignments, mk, wids)
        assert all(a != "keydown" or k != "Left" for (a, w, k) in sent)

    def test_whisper_reply_enter_is_send_not_open(self, monkeypatch, tmp_path):
        """THE bug: mouse-opened whisper, type 'ok', Enter. No stuck block."""
        svc, _, sent = _build_service(monkeypatch, tmp_path)
        enabled, assignments, mk, wids = _args(svc)
        t = time.monotonic()
        for i, ch in enumerate(("o", "k")):
            svc._fsm_handle_keydown(ch, t + i * 0.2, enabled, assignments, mk, wids)
            svc._fsm_handle_keyup(ch, t + i * 0.2 + 0.05, enabled, assignments, mk)
        assert svc._chat_fsm.state is ChatState.CAPTURE_SOFT  # typing suppressed
        svc._fsm_handle_keydown("Return", t + 0.6, enabled, assignments, mk, wids)
        assert svc._chat_fsm.state is ChatState.GRACE          # send, not open
        assert svc.global_chat_active is False
        sent.clear()
        # Movement works again immediately (arrows route instantly in GRACE).
        svc._fsm_handle_keydown("Up", t + 0.8, enabled, assignments, mk, wids)
        assert ("keydown", "t2", "Up") in sent

    def test_unbound_escape_is_terminal_no_action_broadcast(self, monkeypatch, tmp_path):
        """An unbound Escape must never fall through to the ACTION-hold
        broadcast (the block list does not filter that path)."""
        svc, _, sent = _build_service(monkeypatch, tmp_path)
        enabled, assignments, mk, wids = _args(svc)
        assert "Escape" not in mk                   # fresh TTR keymap: book=Alt_L
        svc._fsm_handle_keydown("Escape", time.monotonic(), enabled, assignments, mk, wids)
        assert sent == []
        assert len(svc.holds) == 0

    def test_demote_by_two_key_chord_reroutes(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path)
        enabled, assignments, mk, wids = _args(svc)
        t = time.monotonic()
        svc.global_chat_active = True               # wrong capture (seeded)
        svc._fsm_handle_keydown("Up", t, enabled, assignments, mk, wids)
        svc._fsm_handle_keydown("Left", t + 0.05, enabled, assignments, mk, wids)
        # Both held: physically impossible as chat -> demote on tick.
        svc._fsm_tick(t + 0.5, enabled, assignments, mk)
        assert svc._chat_fsm.state is ChatState.GRACE
        assert svc.global_chat_active is False


# ── mirror modes: bg_chat_open scoping ───────────────────────────────────────

class TestMirrorScoping:
    def test_open_mirrors_and_records_window_ids(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path,
                                      chat_enabled=[True, True])
        enabled, assignments, mk, wids = _args(svc)
        svc._fsm_handle_keydown("Return", time.monotonic(), enabled, assignments, mk, wids)
        assert svc._chat_fsm.state is ChatState.CAPTURE
        assert ("key", "t2", "Return") in sent      # bg box mirrored open
        assert svc._bg_chat_open == {"t2"}

    def test_close_escape_scoped_to_opened_boxes(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path,
                                      windows=["t1", "t2", "t3"],
                                      enabled=[True, True, True],
                                      chat_enabled=[True, True, False])
        enabled, assignments, mk, wids = _args(svc)
        t = time.monotonic()
        svc._fsm_handle_keydown("Return", t, enabled, assignments, mk, wids)
        assert svc._bg_chat_open == {"t2"}          # t3 is chat-blocked
        sent.clear()
        svc._fsm_handle_keydown("Escape", t + 1.0, enabled, assignments, mk, wids)
        escapes = [(a, w) for (a, w, k) in sent if k == "Escape"]
        assert ("key", "t2") in escapes             # scoped close
        assert all(w != "t3" for (_a, w) in escapes)
        assert svc._bg_chat_open == set()

    def test_focused_only_mode_never_records(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path,
                                      chat_enabled=[False, False])
        enabled, assignments, mk, wids = _args(svc)
        svc._fsm_handle_keydown("Return", time.monotonic(), enabled, assignments, mk, wids)
        assert svc._bg_chat_open == set()
        assert all(k != "Return" for (_a, _w, k) in sent)


# ── lifecycle: orphan guard / cleanup / stamp ────────────────────────────────

class TestLifecycle:
    def test_cleanup_orphan_guard_escapes_opened_boxes(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path,
                                      chat_enabled=[True, True])
        enabled, assignments, mk, wids = _args(svc)
        svc._fsm_handle_keydown("Return", time.monotonic(), enabled, assignments, mk, wids)
        assert svc._bg_chat_open == {"t2"}
        sent.clear()
        svc._fsm_route_cleanup()
        assert ("key", "t2", "Escape") in sent
        assert svc._bg_chat_open == set()
        assert svc._chat_fsm.state is ChatState.ROUTE

    def test_release_all_keys_runs_orphan_guard(self, monkeypatch, tmp_path):
        svc, _, sent = _build_service(monkeypatch, tmp_path,
                                      chat_enabled=[True, True])
        enabled, assignments, mk, wids = _args(svc)
        svc._fsm_handle_keydown("Return", time.monotonic(), enabled, assignments, mk, wids)
        sent.clear()
        svc.release_all_keys()
        assert ("key", "t2", "Escape") in sent
        assert svc._chat_fsm.state is ChatState.ROUTE

    def test_run_loop_emits_startup_stamp_and_whisper_flow(self, monkeypatch, tmp_path):
        """End-to-end through the real run loop: stamp on start, then the
        whisper flow (type + Enter) never latches the block."""
        svc, eq, sent = _build_service(monkeypatch, tmp_path)
        logs = []
        # Direct connection: the stamp is emitted from the run-loop thread
        # and no Qt event loop runs here to deliver a queued signal.
        from PySide6.QtCore import Qt
        svc.input_log.connect(logs.append, Qt.ConnectionType.DirectConnection)
        try:
            svc.start()
            deadline = time.monotonic() + 2.0
            while not logs and time.monotonic() < deadline:
                time.sleep(0.01)
            assert any("ChatFSM ACTIVE" in m for m in logs), logs
            # whisper reply: o k taps then Enter
            for ch in ("o", "k"):
                eq.put(("keydown", ch))
                eq.put(("keyup", ch))
            eq.put(("keydown", "Return"))
            eq.put(("keyup", "Return"))
            deadline = time.monotonic() + 2.0
            while svc._chat_fsm.in_capture is False and time.monotonic() < deadline:
                time.sleep(0.005)   # reach CAPTURE_SOFT first (may be brief)
            deadline = time.monotonic() + 3.0
            while svc._chat_fsm.in_capture and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not svc._chat_fsm.in_capture, (
                "send-Enter latched the capture: the legacy bug is back")
            assert svc.global_chat_active is False
        finally:
            svc.stop(wait=True)

    def test_start_resets_stale_capture(self, monkeypatch, tmp_path):
        svc, eq, _ = _build_service(monkeypatch, tmp_path)
        svc.global_chat_active = True
        try:
            svc.start()
            deadline = time.monotonic() + 2.0
            while svc._chat_fsm.in_capture and time.monotonic() < deadline:
                time.sleep(0.01)
            assert svc._chat_fsm.state is not ChatState.CAPTURE
        finally:
            svc.stop(wait=True)


# ── keep-alive gate ──────────────────────────────────────────────────────────

class TestKeepAliveGate:
    def test_skip_focused_during_capture_and_opened_boxes(self, monkeypatch, tmp_path):
        svc, _, _ = _build_service(monkeypatch, tmp_path)
        assert svc.keep_alive_skip_window("t1") is False   # ROUTE: no skips
        svc.global_chat_active = True
        assert svc.keep_alive_skip_window("t1") is True    # focused, capture
        assert svc.keep_alive_skip_window("t2") is False   # bg, no box opened
        svc._bg_chat_open.add("t2")
        assert svc.keep_alive_skip_window("t2") is True

    def test_dispatch_cycle_respects_gate_and_fails_open(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
        from tabs.multitoon._tab import _dispatch_keep_alive_cycle
        from utils.keymap_manager import KeymapManager
        from utils.game_registry import GameRegistry
        monkeypatch.setattr(
            GameRegistry.instance(), "get_game_for_window", lambda wid: "ttr",
        )
        km = KeymapManager()
        wm = SimpleNamespace(get_window_ids=lambda: ["w1", "w2"])
        calls = []
        gated = SimpleNamespace(
            send_keep_alive_to_window=lambda wid, key: calls.append(wid),
            keep_alive_skip_window=lambda wid: wid == "w1",
        )
        fired = _dispatch_keep_alive_cycle("jump", [0, 1], wm, km, gated)
        assert fired == 1 and calls == ["w2"]
        # Bare stub without the gate attribute: historical behavior (fail-open).
        calls.clear()
        bare = SimpleNamespace(
            send_keep_alive_to_window=lambda wid, key: calls.append(wid),
        )
        fired = _dispatch_keep_alive_cycle("jump", [0, 1], wm, km, bare)
        assert fired == 2 and calls == ["w1", "w2"]
