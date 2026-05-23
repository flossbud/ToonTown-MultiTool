"""Covers KeymapTab's active-games detection helpers."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    def __init__(self, **vals):
        self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        self._d.update(vals)
    def get(self, k, default=None):
        return self._d.get(k, default)
    def set(self, k, v):
        self._d[k] = v
    def on_change(self, cb):
        pass


class _FakeCredManager:
    """Minimal stand-in for utils.credentials_manager.CredentialsManager.

    Implements only get_accounts_metadata(game=...) and on_change(...) - the
    surface KeymapTab consumes.
    """
    def __init__(self, ttr=0, cc=0):
        self._ttr_count = ttr
        self._cc_count = cc
    def get_accounts_metadata(self, game=None):
        if game == "ttr":
            return [object()] * self._ttr_count
        if game == "cc":
            return [object()] * self._cc_count
        return [object()] * (self._ttr_count + self._cc_count)
    def on_change(self, cb):
        pass


def _make_tab(qapp, monkeypatch, *, ttr_install=False, cc_install=False,
              cred_manager=None):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager

    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: ttr_install)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: cc_install)
    return KeymapTab(
        KeymapManager(),
        settings_manager=_FakeSettings(),
        credentials_manager=cred_manager,
    )


def test_constructor_accepts_credentials_manager(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cred_manager=_FakeCredManager())
    assert tab.credentials_manager is not None


def test_constructor_credentials_manager_defaults_to_none(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cred_manager=None)
    assert tab.credentials_manager is None


def test_has_accounts_no_credentials_manager(qapp, monkeypatch):
    """Without a cred manager, _has_accounts always returns False."""
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cred_manager=None)
    assert tab._has_accounts("ttr") is False
    assert tab._has_accounts("cc") is False


def test_has_accounts_with_credentials(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr_install=True,
                    cred_manager=_FakeCredManager(ttr=2, cc=0))
    assert tab._has_accounts("ttr") is True
    assert tab._has_accounts("cc") is False


def test_active_games_install_only(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cc_install=False,
                    cred_manager=_FakeCredManager())
    assert tab._active_games() == {"ttr"}


def test_active_games_both_installs(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cc_install=True,
                    cred_manager=_FakeCredManager())
    assert tab._active_games() == {"ttr", "cc"}


def test_active_games_account_only(qapp, monkeypatch):
    """User has no installs detected but has an account for CC.
    Per the spec, that's enough to mark CC active."""
    tab = _make_tab(qapp, monkeypatch, ttr_install=False, cc_install=False,
                    cred_manager=_FakeCredManager(ttr=0, cc=1))
    assert tab._active_games() == {"cc"}


def test_active_games_install_plus_other_account(qapp, monkeypatch):
    """TTR installed + a CC account = both active."""
    tab = _make_tab(qapp, monkeypatch, ttr_install=True, cc_install=False,
                    cred_manager=_FakeCredManager(ttr=0, cc=1))
    assert tab._active_games() == {"ttr", "cc"}


def test_active_games_empty(qapp, monkeypatch):
    """No installs, no accounts. Defensive case."""
    tab = _make_tab(qapp, monkeypatch, ttr_install=False, cc_install=False,
                    cred_manager=_FakeCredManager())
    assert tab._active_games() == set()
