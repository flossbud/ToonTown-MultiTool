"""A password held for one launch: used, never written to the keyring."""

import pytest

from tests.test_credentials_manager_login_state import _ids, make_cm  # noqa: F401
from utils.credentials_manager import LOGIN_FAILED, LOGIN_NONE, LOGIN_SAVED


def _stored(make_cm):
    import keyring
    return dict(keyring.get_keyring()._store)


@pytest.fixture
def cm(make_cm):
    cm = make_cm()
    assert cm.add_account(username="flossbud", password="", game="ttr")
    return cm


def _account(cm):
    return cm.get_account(0)


def test_an_account_added_without_a_password_has_no_login(cm):
    account_id = _ids(cm)[0]
    assert _account(cm).password == ""
    assert cm.login_status(account_id) == LOGIN_NONE


def test_a_held_password_is_what_a_launch_reads(cm, make_cm):
    account_id = _ids(cm)[0]
    before = _stored(make_cm)
    assert cm.hold_password_for_session(account_id, "typed once") is True
    assert _account(cm).password == "typed once"
    assert cm.has_session_password(account_id)
    assert _stored(make_cm) == before               # nothing written to the keyring


def test_a_held_password_does_not_count_as_a_saved_login(cm):
    account_id = _ids(cm)[0]
    cm.hold_password_for_session(account_id, "typed once")
    assert cm.login_status(account_id) == LOGIN_NONE


def test_dropping_it_leaves_the_account_as_it_was(cm):
    account_id = _ids(cm)[0]
    cm.hold_password_for_session(account_id, "typed once")
    cm.drop_session_password(account_id)
    assert _account(cm).password == ""
    assert not cm.has_session_password(account_id)
    cm.drop_session_password(account_id)            # again: harmless


def test_it_is_gone_after_a_restart(cm, make_cm):
    account_id = _ids(cm)[0]
    cm.hold_password_for_session(account_id, "typed once")
    again = make_cm()
    assert again.get_account(0).password == ""
    assert again.login_status(account_id) == LOGIN_NONE


def test_it_expires_like_any_in_memory_password(cm, monkeypatch):
    import utils.credentials_manager as mod
    account_id = _ids(cm)[0]
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    cm.hold_password_for_session(account_id, "typed once")
    clock[0] += cm._fallback_max_age + 1
    assert _account(cm).password == ""
    assert not cm.has_session_password(account_id)


def test_saving_a_login_replaces_a_held_one(cm, make_cm):
    account_id = _ids(cm)[0]
    cm.hold_password_for_session(account_id, "typed once")
    cm.update_account(0, password="kept for good")
    assert _account(cm).password == "kept for good"
    assert not cm.has_session_password(account_id)
    assert cm.login_status(account_id) == LOGIN_SAVED
    assert "kept for good" in _stored(make_cm).values()


def test_a_held_password_does_not_hide_a_saved_one_from_the_status(cm):
    account_id = _ids(cm)[0]
    cm.update_account(0, password="saved")
    cm.hold_password_for_session(account_id, "other")
    assert cm.login_status(account_id) == LOGIN_SAVED
    assert _account(cm).password == "other"         # the held one is used
    cm.drop_session_password(account_id)
    assert _account(cm).password == "saved"


def test_a_rejected_login_still_reads_failed(cm):
    account_id = _ids(cm)[0]
    cm.set_login_failed(account_id, True)
    cm.hold_password_for_session(account_id, "typed once")
    assert cm.login_status(account_id) == LOGIN_FAILED


def test_nothing_is_held_for_an_unknown_account_or_an_empty_password(cm):
    account_id = _ids(cm)[0]
    assert cm.hold_password_for_session("nope", "pw") is False
    assert cm.hold_password_for_session(account_id, "") is False
    assert not cm.has_session_password(account_id)


def test_deleting_the_account_forgets_it(cm):
    account_id = _ids(cm)[0]
    cm.hold_password_for_session(account_id, "typed once")
    cm.delete_account(0)
    assert not cm.has_session_password(account_id)
