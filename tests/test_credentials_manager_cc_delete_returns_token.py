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


def test_clear_all_returns_cc_launcher_tokens(cm):
    """clear_all returns the launcher tokens it cleared so the caller
    can revoke them server-side. TTR accounts contribute nothing; CC
    accounts without stored tokens contribute nothing."""
    cm.add_account(label="CC1", username="cc1@e.com", password="pw", game="cc")
    cm.add_account(label="CC2", username="cc2@e.com", password="pw", game="cc")
    cm.add_account(label="TTR", username="ttr", password="pw", game="ttr")
    cm.add_account(label="CC3", username="cc3@e.com", password="pw", game="cc")  # no token

    cc1_id = cm.get_accounts_metadata()[0].id
    cc2_id = cm.get_accounts_metadata()[1].id
    cm.set_launcher_token(cc1_id, "tok-cc1")
    cm.set_launcher_token(cc2_id, "tok-cc2")
    # CC3 has no token set.

    result = cm.clear_all()
    assert isinstance(result, list)
    assert sorted(result) == ["tok-cc1", "tok-cc2"]
    # All accounts cleared.
    assert cm.get_accounts_metadata() == []
    # Tokens cleared from keyring.
    assert cm.get_launcher_token(cc1_id) == ""
    assert cm.get_launcher_token(cc2_id) == ""


def test_clear_all_empty_returns_empty_list(cm):
    assert cm.clear_all() == []
