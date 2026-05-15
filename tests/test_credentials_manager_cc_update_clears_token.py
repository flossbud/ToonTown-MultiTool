"""update_account clears launcher_token when CC creds change."""

import pytest
from tests.test_credentials_manager_cc_tokens import cm  # reuse fixture


def test_update_cc_password_clears_token(cm):
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    cm.set_launcher_token(cm.get_accounts_metadata()[0].id, "tok-1")
    cm.update_account(0, password="new-pw")
    assert cm.get_accounts_metadata()[0].launcher_token == ""


def test_update_cc_username_clears_token(cm):
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    cm.set_launcher_token(cm.get_accounts_metadata()[0].id, "tok-1")
    cm.update_account(0, username="new@e.com")
    assert cm.get_accounts_metadata()[0].launcher_token == ""


def test_update_cc_label_only_keeps_token(cm):
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    cm.set_launcher_token(cm.get_accounts_metadata()[0].id, "tok-1")
    cm.update_account(0, label="Renamed")
    assert cm.get_accounts_metadata()[0].launcher_token == "tok-1"


def test_update_ttr_password_no_token_op(cm, monkeypatch):
    """For TTR accounts, clear_launcher_token must NOT be called regardless
    of which field changes. This is a real regression guard for the
    `game == "cc"` gate in update_account."""
    cm.add_account(label="Main", username="u", password="pw", game="ttr")
    called = []
    monkeypatch.setattr(cm, "clear_launcher_token", lambda aid: called.append(aid))
    cm.update_account(0, password="new-pw")
    cm.update_account(0, username="new-u")
    cm.update_account(0, label="renamed")
    assert called == []


def test_update_cc_empty_password_keeps_token(cm):
    """Task 11 contract: passing password="" on a CC account discards the
    one-time onboarding password without clearing the freshly-stored
    launcher token. A regression in the `password != ""` carve-out
    would silently break the register-and-login -> token-only handoff."""
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    cm.set_launcher_token(cm.get_accounts_metadata()[0].id, "tok-1")
    cm.update_account(0, password="")
    assert cm.get_accounts_metadata()[0].launcher_token == "tok-1"
