"""Tests for revoke_launcher_token."""

from unittest.mock import MagicMock, patch

import pytest


def test_revoke_returns_true_on_status_true(monkeypatch):
    from services.cc_login_service import revoke_launcher_token, CC_REVOKE_URL

    fake = MagicMock()
    fake.json.return_value = {"status": True, "bad_token": False}
    fake.status_code = 200
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["kw"] = kw
        return fake

    monkeypatch.setattr("requests.post", fake_post)
    result = revoke_launcher_token("token-xyz")
    assert result is True
    assert captured["url"] == CC_REVOKE_URL
    assert captured["kw"]["headers"]["Authorization"] == "Bearer token-xyz"


def test_revoke_returns_false_on_status_false(monkeypatch):
    from services.cc_login_service import revoke_launcher_token
    fake = MagicMock()
    fake.json.return_value = {"status": False, "bad_token": True}
    fake.status_code = 200
    monkeypatch.setattr("requests.post", lambda *a, **kw: fake)
    assert revoke_launcher_token("bad") is False


def test_revoke_never_raises_on_network_error(monkeypatch):
    import requests
    from services.cc_login_service import revoke_launcher_token

    def boom(*a, **kw):
        raise requests.ConnectionError("network down")
    monkeypatch.setattr("requests.post", boom)
    # Must not raise.
    assert revoke_launcher_token("any") is False


def test_revoke_never_raises_on_bad_json(monkeypatch):
    from services.cc_login_service import revoke_launcher_token
    fake = MagicMock()
    fake.json.side_effect = ValueError("not json")
    fake.status_code = 500
    monkeypatch.setattr("requests.post", lambda *a, **kw: fake)
    assert revoke_launcher_token("any") is False
