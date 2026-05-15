"""Tests for CCLoginWorker.login_with_token."""

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
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_login_with_token_success_emits_login_success(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker
    worker = CCLoginWorker()

    login_resp = MagicMock()
    login_resp.json.return_value = {
        "status": True, "success": True, "message": "OK",
        "token": "game-token-abc", "toonstep": False,
    }
    login_resp.status_code = 200
    monkeypatch.setattr("requests.post", lambda *a, **kw: login_resp)

    monkeypatch.setattr(CCLoginWorker, "_fetch_gameserver",
                        lambda self, t: "gs-prd.corporateclash.net:7198")

    captured = []
    worker.login_success.connect(lambda gs, gt: captured.append((gs, gt)))

    worker.login_with_token("launcher-token-xyz")
    assert _wait(lambda: len(captured) > 0), "login_success never fired"
    assert captured[0] == ("gs-prd.corporateclash.net:7198", "game-token-abc")


def test_login_with_token_bad_token_emits_friendly_failure(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker
    worker = CCLoginWorker()

    resp = MagicMock()
    resp.json.return_value = {
        "status": False, "success": False, "bad_token": True,
        "message": "Token invalid",
    }
    resp.status_code = 401
    monkeypatch.setattr("requests.post", lambda *a, **kw: resp)

    failures = []
    worker.login_failed.connect(failures.append)
    worker.login_with_token("revoked-tok")
    assert _wait(lambda: len(failures) > 0)
    assert "Edit" in failures[0] and "password" in failures[0].lower()


def test_login_with_token_passes_bearer_header(qapp, monkeypatch):
    from services.cc_login_service import CCLoginWorker
    worker = CCLoginWorker()
    captured = {}
    resp = MagicMock()
    resp.json.return_value = {"status": True, "success": True, "token": "g"}
    resp.status_code = 200
    def fake_post(url, **kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers", {})
        return resp
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(CCLoginWorker, "_fetch_gameserver",
                        lambda self, t: "gs.example:1")
    worker.login_with_token("my-tok")
    assert _wait(lambda: "url" in captured)
    from services.cc_login_service import CC_LOGIN_URL
    assert captured["url"] == CC_LOGIN_URL
    assert captured["headers"].get("Authorization") == "Bearer my-tok"
