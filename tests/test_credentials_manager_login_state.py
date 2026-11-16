"""Persisted login state: saved | failed | none."""

import json
import os

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest

from utils.credentials_manager import (
    LOGIN_FAILED, LOGIN_FAILED_KEY, LOGIN_NONE, LOGIN_SAVED,
)


@pytest.fixture
def make_cm(tmp_path, monkeypatch):
    """Factory for CredentialsManagers on one tmp config dir and one
    in-process keyring, so a second call is a restart."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(cfg))
    import keyring
    import keyring.core
    from keyring.backend import KeyringBackend

    class _MemoryBackend(KeyringBackend):
        priority = 999

        def __init__(self):
            self._store = {}

        def get_password(self, service, username):
            return self._store.get((service, username))

        def set_password(self, service, username, password):
            self._store[(service, username)] = password

        def delete_password(self, service, username):
            self._store.pop((service, username), None)

    backend = _MemoryBackend()
    prev = keyring.core._keyring_backend
    keyring.set_keyring(backend)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)

    def _make():
        from utils.credentials_manager import CredentialsManager
        cm = CredentialsManager()
        cm._probe_complete = True
        cm._use_keyring = True
        return cm

    _make.path = cfg / "accounts.json"
    yield _make
    keyring.core._keyring_backend = prev


def _ids(cm, game=None):
    return [aid for aid, _, _ in cm.get_accounts_basic(game)]


def test_old_file_loads_unchanged(make_cm):
    old = [{"id": "a1", "label": "A", "username": "a", "game": "ttr"},
           {"id": "c1", "label": "C", "username": "c", "game": "cc"}]
    make_cm.path.write_text(json.dumps(old))
    cm = make_cm()
    assert not cm.is_login_failed("a1")
    assert not cm.is_login_failed("c1")
    assert json.loads(make_cm.path.read_text()) == old


def test_set_and_clear_persist_across_restart(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw", game="ttr")
    aid = _ids(cm)[0]
    assert cm.set_login_failed(aid, True) is True
    assert cm.is_login_failed(aid)
    stored = json.loads(make_cm.path.read_text())
    assert stored[0][LOGIN_FAILED_KEY] is True

    cm2 = make_cm()
    assert cm2.is_login_failed(aid)
    assert cm2.login_status(aid) == LOGIN_FAILED

    assert cm2.set_login_failed(aid, False) is True
    assert LOGIN_FAILED_KEY not in json.loads(make_cm.path.read_text())[0]
    assert not make_cm().is_login_failed(aid)


def test_set_is_idempotent_and_unknown_ids_refused(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    aid = _ids(cm)[0]
    assert cm.set_login_failed(aid, False) is False
    assert cm.set_login_failed(aid, True) is True
    assert cm.set_login_failed(aid, True) is False
    assert cm.set_login_failed("nope", True) is False
    assert cm.set_login_failed("", True) is False
    assert cm.login_status("nope") == LOGIN_NONE


def test_flag_does_not_fire_roster_change(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    fired = []
    cm.on_change(lambda: fired.append(1))
    cm.set_login_failed(_ids(cm)[0], True)
    assert fired == []


def test_status_ttr_saved_and_none(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw", game="ttr")
    cm.add_account(label="B", username="b", password="", game="ttr")
    a, b = _ids(cm)
    assert cm.login_status(a) == LOGIN_SAVED
    assert cm.login_status(b) == LOGIN_NONE


def test_status_cc_token_counts_as_saved(make_cm):
    cm = make_cm()
    cm.add_account(label="C", username="c", password="", game="cc")
    cid = _ids(cm, "cc")[0]
    assert cm.login_status(cid) == LOGIN_NONE
    cm.set_launcher_token(cid, "tok")
    assert cm.login_status(cid) == LOGIN_SAVED


def test_failed_wins_over_saved(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    aid = _ids(cm)[0]
    cm.set_login_failed(aid, True)
    assert cm.login_status(aid) == LOGIN_FAILED


@pytest.mark.parametrize("kwargs,clears", [
    ({"password": "new"}, True),           # Fix login / Edit login
    ({"password": ""}, True),              # Reset / forget the login
    ({"username": "other"}, True),         # a different account name
    ({"username": "a"}, False),            # same username, nothing new
    ({"label": "Renamed"}, False),         # label only
    ({"label": "X", "username": "a", "password": None}, False),
])
def test_saving_a_new_login_clears_failed(make_cm, kwargs, clears):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    aid = _ids(cm)[0]
    cm.set_login_failed(aid, True)
    cm.update_account(0, **kwargs)
    assert cm.is_login_failed(aid) is (not clears)
    assert make_cm().is_login_failed(aid) is (not clears)


def test_new_cc_launcher_token_clears_failed(make_cm):
    cm = make_cm()
    cm.add_account(label="C", username="c", password="pw", game="cc")
    cid = _ids(cm, "cc")[0]
    cm.set_login_failed(cid, True)
    cm.set_launcher_token(cid, "fresh")
    assert not cm.is_login_failed(cid)


def test_flag_survives_reorder_and_is_dropped_with_account(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    cm.add_account(label="B", username="b", password="pw")
    a, b = _ids(cm)
    cm.set_login_failed(b, True)
    assert cm.reorder_game("ttr", [b, a])
    assert make_cm().is_login_failed(b)
    cm.delete_account(0)
    assert not cm.is_login_failed(b)
    assert all(LOGIN_FAILED_KEY not in e for e in json.loads(make_cm.path.read_text()))


def test_reason_stored_cleared_and_capped(make_cm):
    from utils.credentials_manager import LOGIN_FAILED_REASON_KEY
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    aid = _ids(cm)[0]
    assert cm.login_failed_reason(aid) is None
    assert cm.set_login_failed(aid, True, "  Closed for maintenance.  ") is True
    assert make_cm().login_failed_reason(aid) == "Closed for maintenance."
    assert cm.set_login_failed(aid, True, "Closed for maintenance.") is False
    assert cm.set_login_failed(aid, True, "Wrong password") is True
    assert cm.login_failed_reason(aid) == "Wrong password"
    cm.set_login_failed(aid, True, "x" * 1000)
    assert len(cm.login_failed_reason(aid)) == 300
    cm.set_login_failed(aid, True, None)
    assert cm.login_failed_reason(aid) is None
    assert cm.is_login_failed(aid)
    cm.set_login_failed(aid, True, "again")
    cm.set_login_failed(aid, False)
    assert cm.login_failed_reason(aid) is None
    assert all(LOGIN_FAILED_REASON_KEY not in e
               for e in json.loads(make_cm.path.read_text()))


def test_new_login_clears_reason(make_cm):
    cm = make_cm()
    cm.add_account(label="A", username="a", password="pw")
    aid = _ids(cm)[0]
    cm.set_login_failed(aid, True, "nope")
    cm.update_account(0, password="new")
    assert cm.login_failed_reason(aid) is None
