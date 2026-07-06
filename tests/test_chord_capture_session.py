"""Chord-capture keyboard session + input holiday (the cocoa deaf-capture fix).

Root cause (live 2026-07-05): overlay surfaces carry
Qt.WindowDoesNotAcceptFocus, which on cocoa pins canBecomeKeyWindow to NO -
the window server never delivers a keyboard event to the floating settings
panel, so the capture button was deaf and every key beeped off the still-key
app. The fix brackets each capture with (a) a Spotlight-pattern key-window
session on the panel and (b) a global input holiday (chord_capture_state)
that stands down the session tap, the router and the hotkey providers.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
      ./venv/bin/python -m pytest tests/test_chord_capture_session.py -q
"""
import os
import queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from utils import chord_capture_state


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_capture_state():
    yield
    chord_capture_state.set_active(False)


# -- chord_capture_state ---------------------------------------------------

def test_state_edges_notify_listeners_once():
    seen = []
    chord_capture_state.register(seen.append)
    try:
        assert not chord_capture_state.is_active()
        chord_capture_state.set_active(True)
        chord_capture_state.set_active(True)      # same value: no re-fire
        chord_capture_state.set_active(False)
        assert seen == [True, False]
    finally:
        chord_capture_state.unregister(seen.append)


def test_state_listener_errors_never_break_capture():
    def boom(_):
        raise RuntimeError("listener bug")
    chord_capture_state.register(boom)
    try:
        chord_capture_state.set_active(True)      # must not raise
        assert chord_capture_state.is_active()
    finally:
        chord_capture_state.unregister(boom)


def test_state_unregister_is_idempotent():
    def cb(_):
        pass
    chord_capture_state.register(cb)
    chord_capture_state.unregister(cb)
    chord_capture_state.unregister(cb)            # absent: no error


# -- ChordCaptureButton wiring ----------------------------------------------

def _wire_spies(monkeypatch):
    from utils import hotkey_capture as hc
    calls = []
    monkeypatch.setattr(hc.key_session, "begin",
                        lambda w: calls.append(("begin", w)) or True)
    monkeypatch.setattr(hc.key_session, "end",
                        lambda w: calls.append(("end", w)))
    return calls


def test_begin_capture_opens_session_and_holiday(qapp, monkeypatch):
    from utils.hotkey_capture import ChordCaptureButton
    calls = _wire_spies(monkeypatch)
    b = ChordCaptureButton("F5", on_chord=lambda c: None)
    b.begin_capture()
    assert chord_capture_state.is_active()
    assert calls == [("begin", b)]
    b._end_capture()
    assert not chord_capture_state.is_active()
    assert calls == [("begin", b), ("end", b)]


def test_every_capture_end_path_closes_session(qapp, monkeypatch):
    from PySide6.QtGui import QFocusEvent, QKeyEvent
    from utils.hotkey_capture import ChordCaptureButton
    calls = _wire_spies(monkeypatch)

    # Esc cancel
    b = ChordCaptureButton("F5", on_chord=lambda c: None)
    b.begin_capture()
    b.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape,
                              Qt.NoModifier, "", False, 1))
    assert not chord_capture_state.is_active()
    assert calls[-1] == ("end", b)

    # commit on release
    seen = []
    b2 = ChordCaptureButton(None, on_chord=seen.append)
    b2.begin_capture()
    b2.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_H,
                               Qt.ControlModifier, "h", False, 1))
    b2.keyReleaseEvent(QKeyEvent(QKeyEvent.KeyRelease, Qt.Key_H,
                                 Qt.ControlModifier, "h", False, 1))
    assert seen == ["ctrl+h"]
    assert not chord_capture_state.is_active()
    assert calls[-1] == ("end", b2)

    # focus-out cancel
    b3 = ChordCaptureButton("F5", on_chord=lambda c: None)
    b3.begin_capture()
    b3.focusOutEvent(QFocusEvent(QFocusEvent.FocusOut))
    assert not chord_capture_state.is_active()
    assert calls[-1] == ("end", b3)


# -- key_session seam --------------------------------------------------------

def test_key_session_noop_for_focusable_windows(qapp, monkeypatch):
    from utils.overlay import key_session
    hits = []
    monkeypatch.setattr(key_session, "_get_backend",
                        lambda: hits.append("backend") or object())
    w = QWidget()  # plain focusable top-level: no session needed
    assert key_session.begin(w) is False
    key_session.end(w)
    assert hits == []  # never even resolved a backend


class _FakeSessionBackend:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def begin_key_session(self, w):
        self.calls.append(("begin", w))
        return self.ok

    def end_key_session(self, w):
        self.calls.append(("end", w))


def _unfocusable_window():
    w = QWidget()
    w.setWindowFlags(Qt.Window | Qt.FramelessWindowHint
                     | Qt.WindowDoesNotAcceptFocus)
    return w


def test_key_session_routes_unfocusable_window_to_backend(qapp, monkeypatch):
    from utils.overlay import key_session
    be = _FakeSessionBackend()
    monkeypatch.setattr(key_session, "_get_backend", lambda: be)
    w = _unfocusable_window()
    assert key_session.begin(w) is True
    key_session.end(w)
    assert be.calls == [("begin", w), ("end", w)]


def test_key_session_kill_switch(qapp, monkeypatch):
    from utils.overlay import key_session
    be = _FakeSessionBackend()
    monkeypatch.setattr(key_session, "_get_backend", lambda: be)
    monkeypatch.setenv("TTMT_NO_KEY_SESSION", "1")
    assert key_session.begin(_unfocusable_window()) is False
    assert be.calls == []


def test_key_session_backend_without_sessions_is_noop(qapp, monkeypatch):
    from utils.overlay import key_session
    from utils.overlay.backend import NoOpOverlayBackend
    monkeypatch.setattr(key_session, "_get_backend", NoOpOverlayBackend)
    w = _unfocusable_window()
    assert key_session.begin(w) is False
    key_session.end(w)  # must not raise


# -- MacOSOverlayBackend session membership (pure logic, fakes) --------------

class _FakeNSWin:
    def __init__(self):
        self.key = False
        self.order_calls = []
        self.first_responder = None
        self._view = object()

    def makeKeyWindow(self):
        self.key = True

    def isKeyWindow(self):
        return self.key

    def contentView(self):
        return self._view

    def makeFirstResponder_(self, view):
        self.first_responder = view

    def orderOut_(self, _):
        self.order_calls.append("out")
        self.key = False

    def orderFrontRegardless(self):
        self.order_calls.append("front")


def _session_backend(monkeypatch, win):
    from utils.overlay import macos_backend as mb
    be = mb.MacOSOverlayBackend()
    monkeypatch.setattr(be, "is_available", lambda: True)
    monkeypatch.setattr(be, "_nswindow", lambda w: win)
    monkeypatch.setattr(be, "_exempt_frame_constrain", lambda w: True)
    monkeypatch.setattr(be, "_exempt_view_responder", lambda v: True)
    monkeypatch.setattr(mb, "_KEY_METHOD_OK", True)
    monkeypatch.setattr(mb, "_objc_ptr", id)
    return mb, be


def test_macos_begin_adds_membership_and_makes_key(qapp, monkeypatch):
    win = _FakeNSWin()
    mb, be = _session_backend(monkeypatch, win)
    assert be.begin_key_session(object()) is True
    assert id(win) in mb._KEY_SESSION_WINDOWS
    assert win.key
    # the content view was made first responder AFTER membership, so the
    # acceptsFirstResponder override said YES (AppKit consults it)
    assert win.first_responder is win.contentView()
    be.end_key_session(object())
    assert id(win) not in mb._KEY_SESSION_WINDOWS
    # key window at end -> hand key back via the orderOut/orderFront dance
    assert win.order_calls == ["out", "front"]


def test_macos_begin_fails_without_view_responder(qapp, monkeypatch):
    """A key window whose view refuses first responder still drops every
    keyDown (the live beep) - the session must report NOT established."""
    win = _FakeNSWin()
    mb, be = _session_backend(monkeypatch, win)
    monkeypatch.setattr(be, "_exempt_view_responder", lambda v: False)
    assert be.begin_key_session(object()) is False
    assert win.first_responder is None


def test_macos_end_skips_dance_when_not_key(qapp, monkeypatch):
    win = _FakeNSWin()
    mb, be = _session_backend(monkeypatch, win)
    be.begin_key_session(object())
    win.key = False  # the user clicked away; key already moved
    be.end_key_session(object())
    assert win.order_calls == []


def test_macos_begin_refused_without_key_method(qapp, monkeypatch):
    win = _FakeNSWin()
    mb, be = _session_backend(monkeypatch, win)
    monkeypatch.setattr(mb, "_KEY_METHOD_OK", False)
    assert be.begin_key_session(object()) is False
    assert not win.key


def test_macos_can_become_key_membership_contract(qapp, monkeypatch):
    """The override and the session set agree through _objc_ptr: membership
    IS the canBecomeKeyWindow answer."""
    from utils.overlay import macos_backend as mb
    monkeypatch.setattr(mb, "_objc_ptr", id)
    win = _FakeNSWin()
    assert id(win) not in mb._KEY_SESSION_WINDOWS
    mb._KEY_SESSION_WINDOWS.add(id(win))
    try:
        assert id(win) in mb._KEY_SESSION_WINDOWS
    finally:
        mb._KEY_SESSION_WINDOWS.discard(id(win))


# -- router / tap gates -------------------------------------------------------

def _fake_key(char=None, name=None, vk=None):
    class _K:
        pass
    k = _K()
    k.char = char
    k.name = name
    k.vk = vk
    return k


def _router(monkeypatch, hook=None):
    from unittest.mock import MagicMock
    from services.hotkey_manager import HotkeyManager
    wm = MagicMock()
    wm.should_capture_input.return_value = True
    q = queue.Queue(maxsize=10)
    hm = HotkeyManager(wm, q, hotkey_hook=hook, fire_hotkeys=True)
    return hm, q


def test_router_drops_keydowns_during_capture(qapp):
    fired = []
    hook = lambda mods, keys: "app.refresh" if keys == frozenset({"F5"}) else None
    hm, q = _router(None, hook=hook)
    hm.hotkey_triggered.connect(fired.append)
    chord_capture_state.set_active(True)
    assert hm.on_global_key_press(_fake_key(name="f5")) is None
    assert fired == [] and q.qsize() == 0     # no fire, no enqueue
    chord_capture_state.set_active(False)
    hm.on_global_key_press(_fake_key(name="f5"))
    assert fired == ["app.refresh"]           # normal behavior restored


def test_router_keyups_still_flow_during_capture(qapp):
    """A hold enqueued BEFORE the capture began must still drain: keyup
    enqueue is deliberately ungated."""
    hm, q = _router(None)
    hm.on_global_key_press(_fake_key(char="w"))
    assert q.qsize() == 1
    chord_capture_state.set_active(True)
    hm.on_global_key_release(_fake_key(char="w"))
    assert q.qsize() == 2                     # the keyup joined the queue


def test_darwin_intercept_passes_fresh_downs_during_capture(qapp):
    """With capture active, the suppress predicate is never consulted for a
    fresh keydown - the chord must reach the key window."""
    import tests.test_hotkey_manager_darwin as td
    q = td.FakeQuartz()
    hk = td._make_hk(q, suppress_predicate=lambda ks: True,
                     game_pids=frozenset({101}))
    ev = td._event(keycode=td.KC_W, target_pid=101)
    chord_capture_state.set_active(True)
    assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev   # NOT suppressed
    assert "w" not in hk._suppressed_down
    chord_capture_state.set_active(False)
    assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is None  # suppression back


def test_darwin_intercept_keeps_pairing_law_across_capture_begin(qapp):
    """A hold suppressed BEFORE capture began still gets its release eaten
    (its down never reached the capture widget either)."""
    import tests.test_hotkey_manager_darwin as td
    q = td.FakeQuartz()
    hk = td._make_hk(q, suppress_predicate=lambda ks: True,
                     game_pids=frozenset({101}))
    ev = td._event(keycode=td.KC_W, target_pid=101)
    assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is None  # suppressed hold
    chord_capture_state.set_active(True)
    assert hk._darwin_intercept(q.kCGEventKeyUp, ev) is None    # paired eat
    assert "w" not in hk._suppressed_down                       # pair closed


def test_input_service_drains_on_capture_begin(qapp, monkeypatch, tmp_path):
    """The service's registered edge listener releases all held keys the
    moment a capture begins (the V2 stuck-key class)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from unittest.mock import MagicMock
    from services.input_service import InputService
    wm = MagicMock()
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [],
        get_movement_modes=lambda: {},
        get_event_queue_func=lambda: queue.Queue(),
    )
    try:
        drained = []
        monkeypatch.setattr(svc, "release_all_keys",
                            lambda: drained.append(1))
        chord_capture_state.set_active(True)
        assert drained == [1]
        chord_capture_state.set_active(False)
        assert drained == [1]                 # end edge does not re-drain
    finally:
        svc.shutdown()
        chord_capture_state.set_active(False)
