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


def test_update_ttr_password_no_token_op(cm):
    """TTR accounts don't have tokens to clear; update is a no-op for token."""
    cm.add_account(label="Main", username="u", password="pw", game="ttr")
    cm.update_account(0, password="new-pw")
    assert cm.get_accounts_metadata()[0].launcher_token == ""
