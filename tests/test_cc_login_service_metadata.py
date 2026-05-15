"""Tests for CCLoginWorker._fetch_gameserver."""

from unittest.mock import MagicMock
import pytest


@pytest.fixture
def worker(qapp):
    from services.cc_login_service import CCLoginWorker
    return CCLoginWorker()


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def test_fetch_gameserver_takes_first_realm(worker, monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {
        "realms": [
            {"hostname": "gs-prd.corporateclash.net:7198"},
            {"hostname": "gs-test.corporateclash.net:7199"},
        ],
        "bad_token": False,
    }
    fake.status_code = 200
    monkeypatch.setattr("requests.get", lambda *a, **kw: fake)
    assert worker._fetch_gameserver("tok") == "gs-prd.corporateclash.net:7198"


def test_fetch_gameserver_empty_realms_falls_back(worker, monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {"realms": [], "bad_token": False}
    fake.status_code = 200
    monkeypatch.setattr("requests.get", lambda *a, **kw: fake)
    from services.cc_login_service import CC_FALLBACK_GAMESERVER
    assert worker._fetch_gameserver("tok") == CC_FALLBACK_GAMESERVER


def test_fetch_gameserver_network_error_falls_back(worker, monkeypatch):
    import requests
    def boom(*a, **kw):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr("requests.get", boom)
    from services.cc_login_service import CC_FALLBACK_GAMESERVER
    assert worker._fetch_gameserver("tok") == CC_FALLBACK_GAMESERVER


def test_fetch_gameserver_bad_token_falls_back(worker, monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {"error": "Unauthorized", "bad_token": True}
    fake.status_code = 401
    monkeypatch.setattr("requests.get", lambda *a, **kw: fake)
    from services.cc_login_service import CC_FALLBACK_GAMESERVER
    assert worker._fetch_gameserver("bad-tok") == CC_FALLBACK_GAMESERVER
