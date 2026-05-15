"""delete_account hands the previously-stored launcher token to the caller."""

import pytest
from tests.test_credentials_manager_cc_tokens import cm  # reuse fixture


def test_delete_cc_returns_account_id_and_token(cm):
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    acct_id = cm.get_accounts_metadata()[0].id
    cm.set_launcher_token(acct_id, "tok-to-revoke")
    result = cm.delete_account(0)
    assert result == (acct_id, "tok-to-revoke")
    assert cm.get_launcher_token(acct_id) == ""  # also cleared locally


def test_delete_ttr_returns_id_and_none(cm):
    cm.add_account(label="TTR", username="u", password="pw", game="ttr")
    acct_id = cm.get_accounts_metadata()[0].id
    result = cm.delete_account(0)
    assert result == (acct_id, None)


def test_delete_cc_without_token_returns_id_and_none(cm):
    cm.add_account(label="Main", username="u@e.com", password="pw", game="cc")
    acct_id = cm.get_accounts_metadata()[0].id
    result = cm.delete_account(0)
    assert result == (acct_id, None)


def test_delete_out_of_range_returns_none(cm):
    """Out-of-range index returns None, not a tuple. Task 13's revoke
    wiring will use `if result is not None:` to distinguish 'nothing to
    delete' from 'delete succeeded, possibly with token to revoke'."""
    assert cm.delete_account(0) is None      # empty list
    assert cm.delete_account(-1) is None     # negative
    cm.add_account(label="X", username="u", password="pw", game="ttr")
    assert cm.delete_account(99) is None     # past end with non-empty list
