"""macOS backend mouse-method tests (fake delivery engine; no PyObjC)."""
from utils.macos_backend import MacOSBackend


class _FakeEngine:
    def __init__(self, available=True, psn=b"PSN"):
        self._available = available
        self._psn = psn
        self.calls = []

    @property
    def available(self):
        return self._available

    def resolve_psn(self, wid):
        return self._psn

    def resolve_owner(self, wid):
        return 555

    def press(self, pid, wid, psn, win, screen):
        self.calls.append(("press", pid, wid, psn, win, screen)); return True

    def motion(self, pid, wid, psn, win, screen, dragging):
        self.calls.append(("motion", pid, wid, psn, win, screen, dragging)); return True

    def release(self, pid, wid, psn, win, screen):
        self.calls.append(("release", pid, wid, psn, win, screen)); return True


def _backend(monkeypatch, engine, pid=4242, access=True):
    b = MacOSBackend()
    b._delivery = engine
    monkeypatch.setattr(b, "_resolve_pid", lambda wid: pid)
    monkeypatch.setattr(b, "has_post_access", lambda: access)
    monkeypatch.setattr(b, "_creation_identity", lambda pid: "C1")  # stable launch token
    return b


def test_press_binds_and_delivers(monkeypatch):
    eng = _FakeEngine(psn=b"PSNX")
    b = _backend(monkeypatch, eng)
    assert b.send_button_press("77", 100, 50, 1100, 80, button=1, state=0, time=0) is True
    assert eng.calls[0] == ("press", 4242, 77, b"PSNX", (100, 50), (1100, 80))
    assert b._bindings["77"] == (4242, 77, b"PSNX", 555, "C1")   # pid, wid, psn, owner, creation


def test_press_false_when_psn_unresolved(monkeypatch):
    eng = _FakeEngine()
    monkeypatch.setattr(eng, "resolve_psn", lambda wid: None)
    b = _backend(monkeypatch, eng)
    assert b.send_button_press("77", 1, 1, 1, 1) is False
    assert "77" not in b._bindings


def test_drag_uses_binding_hover_fresh_resolves(monkeypatch):
    eng = _FakeEngine()
    b = _backend(monkeypatch, eng)
    b.send_button_press("77", 1, 1, 1, 1)
    eng.calls.clear()
    b.send_motion("77", 10, 10, 20, 20, state=0x100, time=0)   # Button1 held -> drag
    assert eng.calls[-1][0] == "motion" and eng.calls[-1][-1] is True
    eng.calls.clear()
    b.send_motion("77", 11, 11, 21, 21, state=0, time=0)       # no button -> hover
    assert eng.calls[-1][0] == "motion" and eng.calls[-1][-1] is False


def test_release_uses_binding_and_clears(monkeypatch):
    eng = _FakeEngine()
    b = _backend(monkeypatch, eng)
    b.send_button_press("77", 1, 1, 1, 1)
    eng.calls.clear()
    assert b.send_button_release("77", 2, 2, 3, 3) is True
    assert eng.calls[-1][0] == "release"
    assert "77" not in b._bindings


def test_release_without_binding_returns_false_no_fresh_resolve(monkeypatch):
    eng = _FakeEngine()
    b = _backend(monkeypatch, eng)
    assert b.send_button_release("99", 1, 1, 1, 1) is False
    assert eng.calls == []


def test_press_failure_leaves_no_binding(monkeypatch):
    eng = _FakeEngine()
    monkeypatch.setattr(eng, "press", lambda *a: False)
    b = _backend(monkeypatch, eng)
    assert b.send_button_press("77", 1, 1, 1, 1) is False
    assert "77" not in b._bindings


def test_release_detects_pid_reuse(monkeypatch):
    # All TTR toons share one bundle, so a different toon could reuse a window id.
    eng = _FakeEngine()
    b = _backend(monkeypatch, eng)
    b.send_button_press("77", 1, 1, 1, 1)                            # binds creation="C1", owner=555
    eng.calls.clear()
    monkeypatch.setattr(b, "_creation_identity", lambda pid: "C2")   # wid now owned by another process
    assert b.send_button_release("77", 2, 2, 3, 3) is False          # do NOT up into a stranger
    assert all(call[0] != "release" for call in eng.calls)
    assert "77" not in b._bindings                                   # binding cleared regardless


def test_drag_without_binding_is_dropped(monkeypatch):
    eng = _FakeEngine()
    b = _backend(monkeypatch, eng)
    # Button1 held but no prior press binding -> dropped, NOT fresh-resolved (spec §3.2).
    assert b.send_motion("88", 5, 5, 6, 6, state=0x100, time=0) is False
    assert eng.calls == []


def test_mouse_delivery_ready_reason(monkeypatch):
    ready, reason = _backend(monkeypatch, _FakeEngine(True), access=False).mouse_delivery_ready()
    assert ready is False and "access" in reason.lower()
    ready, reason = _backend(monkeypatch, _FakeEngine(False), access=True).mouse_delivery_ready()
    assert ready is False and reason
    assert _backend(monkeypatch, _FakeEngine(True), access=True).mouse_delivery_ready() == (True, None)


def test_mouse_delivery_ready_fails_closed_on_probe_exception(monkeypatch):
    # the engine's lazy import (or .available) raising must yield (False, reason), never ready
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    def _boom():
        raise ImportError("no SkyLight on this host")
    monkeypatch.setattr(b, "_engine", _boom)
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert "probe failed" in reason and "ImportError" in reason
