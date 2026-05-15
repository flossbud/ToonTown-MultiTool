"""Tests for the _friendly_name builder."""

from services.cc_login_service import _friendly_name


def test_friendly_name_no_label(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "linuxmint")
    assert _friendly_name() == "ToontownMultiTool (linuxmint)"


def test_friendly_name_with_label(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "linuxmint")
    assert _friendly_name("MainToon") == "ToontownMultiTool (linuxmint) - MainToon"


def test_friendly_name_empty_label_falls_back(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "host")
    assert _friendly_name("") == "ToontownMultiTool (host)"
