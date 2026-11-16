"""Only a server refusing the credentials marks a login as failed; network,
decode, queue and 2FA failures do not. Covers both workers and the launch
tab's hook."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(predicate, timeout=2.0):
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _resp(body, status=200):
    r = MagicMock()
    r.json.return_value = body
    r.status_code = status
    r.text = str(body)
    return r


def _bad_json():
    r = MagicMock()
    r.json.side_effect = ValueError("not json")
    r.status_code = 502
    r.text = "<html>"
    return r


def _post_raising(*a, **kw):
    raise requests.ConnectionError("down")


def _run_and_wait_failure(worker, start):
    failed = []
    worker.login_failed.connect(lambda m: failed.append(m))
    start()
    assert _wait(lambda: failed), "login_failed never fired"
    return failed[0]


# ── TTR ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("post,rejected", [
    (lambda *a, **kw: _resp({"success": "false",
                             "banner": "Incorrect username and/or password."}), True),
    (_post_raising, False),
    (lambda *a, **kw: _bad_json(), False),
])
def test_ttr_login(qapp, monkeypatch, post, rejected):
    from services.ttr_login_service import TTRLoginWorker
    monkeypatch.setattr("requests.post", post)
    w = TTRLoginWorker()
    _run_and_wait_failure(w, lambda: w.login("user", "pw"))
    assert w.credentials_rejected is rejected


def test_ttr_wrong_2fa_code_is_not_a_password_rejection(qapp, monkeypatch):
    from services.ttr_login_service import TTRLoginWorker
    w = TTRLoginWorker()
    w._response_token = "auth-token"
    monkeypatch.setattr("requests.post", lambda *a, **kw: _resp(
        {"success": "false", "banner": "Invalid authenticator token."}))
    _run_and_wait_failure(w, lambda: w.submit_2fa("000000"))
    assert w.credentials_rejected is False


def test_ttr_new_attempt_resets_the_flag(qapp, monkeypatch):
    from services.ttr_login_service import TTRLoginWorker
    w = TTRLoginWorker()
    w.credentials_rejected = True
    monkeypatch.setattr("requests.post", _post_raising)
    _run_and_wait_failure(w, lambda: w.login("user", "pw"))
    assert w.credentials_rejected is False


# ── CC ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("post,rejected", [
    (lambda *a, **kw: _resp({"status": False, "message": "Invalid credentials"}, 401), True),
    (_post_raising, False),
    (lambda *a, **kw: _bad_json(), False),
])
def test_cc_register(qapp, monkeypatch, post, rejected):
    from services.cc_login_service import CCLoginWorker
    monkeypatch.setattr("requests.post", post)
    w = CCLoginWorker()
    _run_and_wait_failure(w, lambda: w.register_and_login("user", "pw"))
    assert w.credentials_rejected is rejected


@pytest.mark.parametrize("post,rejected", [
    (lambda *a, **kw: _resp({"status": False, "bad_token": True,
                             "message": "Token invalid"}, 401), True),
    (lambda *a, **kw: _resp({"status": False, "message": "Maintenance"}, 503), False),
    (_post_raising, False),
])
def test_cc_login_with_token(qapp, monkeypatch, post, rejected):
    from services.cc_login_service import CCLoginWorker
    monkeypatch.setattr("requests.post", post)
    w = CCLoginWorker()
    _run_and_wait_failure(w, lambda: w.login_with_token("tok"))
    assert w.credentials_rejected is rejected


# ── Launch tab hook ─────────────────────────────────────────────────────────

def _tab_stub(cred_manager, worker, account_id="acct-1"):
    from tabs.launch_tab import LaunchTab
    tab = SimpleNamespace(
        _slots={"ttr": {account_id: SimpleNamespace(worker=worker)}},
        cred_manager=cred_manager,
        log=lambda *a, **kw: None,
        _position_of=lambda g, a: 1,
        _update_status=lambda *a, **kw: None,
        _show_failure_dialog=lambda *a, **kw: None,
    )
    tab._record_login_rejected = (
        lambda aid, rejected: LaunchTab._record_login_rejected(tab, aid, rejected))
    return LaunchTab, tab


@pytest.mark.parametrize("rejected", [True, False])
def test_on_login_failed_records_only_rejections(qapp, rejected):
    worker = SimpleNamespace(credentials_rejected=rejected)
    cm = MagicMock()
    LaunchTab, tab = _tab_stub(cm, worker)
    LaunchTab._on_login_failed(tab, "ttr", "acct-1", worker, "msg")
    if rejected:
        cm.set_login_failed.assert_called_once_with("acct-1", True)
    else:
        cm.set_login_failed.assert_not_called()


def test_on_login_failed_ignores_a_mock_worker_attribute(qapp):
    worker = MagicMock()          # attribute exists but is not literally True
    cm = MagicMock()
    LaunchTab, tab = _tab_stub(cm, worker)
    LaunchTab._on_login_failed(tab, "ttr", "acct-1", worker, "msg")
    cm.set_login_failed.assert_not_called()


def test_stale_worker_records_nothing(qapp):
    current, stale = SimpleNamespace(), SimpleNamespace(credentials_rejected=True)
    cm = MagicMock()
    LaunchTab, tab = _tab_stub(cm, current)
    LaunchTab._on_login_failed(tab, "ttr", "acct-1", stale, "msg")
    cm.set_login_failed.assert_not_called()


def test_record_tolerates_managers_without_the_api(qapp):
    from tabs.launch_tab import LaunchTab
    tab = SimpleNamespace(cred_manager=object())
    LaunchTab._record_login_rejected(tab, "acct-1", True)    # no raise
