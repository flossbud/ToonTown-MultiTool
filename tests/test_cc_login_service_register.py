"""Tests for CCLoginWorker.register_and_login."""

import time
from unittest.mock import MagicMock
import pytest


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _wait(predicate, timeout=2.0):
    """Busy-wait helper. Calls QCoreApplication.processEvents() each tick
    so cross-thread queued Qt signals (worker daemon thread -> main thread
    slots) actually deliver during the wait."""
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_register_success_emits_launcher_token_then_login_success(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker

    call_log = []
    def fake_post(url, **kw):
        call_log.append(url)
        resp = MagicMock()
        resp.status_code = 200
        if "register" in url:
            resp.json.return_value = {
                "status": True, "token": "launcher-tok",
                "message": "ok", "id": 42, "toonstep": False,
            }
        else:
            resp.json.return_value = {
                "status": True, "success": True, "token": "game-tok",
            }
        return resp
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(CCLoginWorker, "_fetch_gameserver",
                        lambda self, t: "gs.example:1")

    worker = CCLoginWorker()
    tokens = []
    successes = []
    worker.launcher_token_obtained.connect(tokens.append)
    worker.login_success.connect(lambda gs, gt: successes.append((gs, gt)))

    worker.register_and_login("user@example.com", "pw", label="Main")
    assert _wait(lambda: tokens and successes)
    assert tokens[0] == "launcher-tok"
    assert successes[0] == ("gs.example:1", "game-tok")
    assert "register" in call_log[0]
    assert "login" in call_log[1]


def test_register_failure_emits_login_failed_with_api_message(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": False, "message": "Invalid username or password.",
    }
    monkeypatch.setattr("requests.post", lambda *a, **kw: resp)
    worker = CCLoginWorker()
    failures = []
    worker.login_failed.connect(failures.append)
    worker.register_and_login("bad@e.com", "wrong")
    assert _wait(lambda: failures)
    assert "Invalid username or password" in failures[0]


def test_register_passes_friendly_username_password_to_api(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker, CC_REGISTER_URL
    captured = {}
    def fake_post(url, **kw):
        captured.setdefault("calls", []).append((url, kw))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": True, "token": "t"}
        return resp
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(CCLoginWorker, "_fetch_gameserver",
                        lambda self, t: "gs:1")
    monkeypatch.setattr("socket.gethostname", lambda: "myhost")
    worker = CCLoginWorker()
    worker.register_and_login("u@e.com", "pw", label="Main")
    assert _wait(lambda: any(c[0] == CC_REGISTER_URL for c in captured.get("calls", [])))
    register_call = next(c for c in captured["calls"] if c[0] == CC_REGISTER_URL)
    body = register_call[1]["json"]
    assert body["username"] == "u@e.com"
    assert body["password"] == "pw"
    assert body["friendly"] == "ToontownMultiTool (myhost) - Main"


def test_register_2fa_hint_in_message_routes_to_need_2fa(qapp, monkeypatch):
    """Defensive: if CC's response message contains '2fa', surface that
    verbatim via login_failed so the user knows where to look."""
    from services.cc_login_service import CCLoginWorker
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": False, "message": "2FA required for this account."}
    monkeypatch.setattr("requests.post", lambda *a, **kw: resp)
    worker = CCLoginWorker()
    failures = []
    worker.login_failed.connect(failures.append)
    worker.register_and_login("u@e.com", "pw")
    assert _wait(lambda: failures)
    assert "2FA required for this account." in failures[0]
