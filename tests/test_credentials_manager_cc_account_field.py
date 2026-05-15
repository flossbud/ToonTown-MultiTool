"""AccountCredential.launcher_token is populated for CC accounts."""

import pytest
from tests.test_credentials_manager_cc_tokens import cm  # reuse fixture


def test_cc_account_has_launcher_token_attribute(cm):
    """The dataclass exposes launcher_token, default ''."""
    cm.add_account(label="Main", username="user@example.com",
                   password="pw", game="cc")
    acct = cm.get_accounts_metadata()[0]
    assert hasattr(acct, "launcher_token")
    assert acct.launcher_token == ""


def test_cc_account_launcher_token_lazy_loads_from_keyring(cm):
    cm.add_account(label="Main", username="user@example.com",
                   password="pw", game="cc")
    acct_id = cm.get_accounts_metadata()[0].id
    cm.set_launcher_token(acct_id, "stored-token")
    acct = cm.get_accounts_metadata()[0]
    assert acct.launcher_token == "stored-token"


def test_ttr_account_launcher_token_always_empty(cm):
    """TTR accounts don't use launcher tokens — field stays empty even if
    something ever sat in the keyring with the same id."""
    cm.add_account(label="MyTTR", username="u@e.com",
                   password="pw", game="ttr")
    acct = cm.get_accounts_metadata()[0]
    assert acct.launcher_token == ""
