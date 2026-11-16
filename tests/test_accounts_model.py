"""The Accounts sheet's model, copy and in-memory backend."""

import pytest

from utils.widgets.launchpad import accounts_model as m
from utils.widgets.launchpad.accounts_backend import FakeAccountsBackend
from utils.widgets.launchpad.accounts_model import (
    LOGIN_FAILED, LOGIN_NONE, LOGIN_SAVED, AccountInfo, ToonInfo,
)

NOW = 2_000_000_000.0
DAY = 86400.0


def toons(n, played=None):
    return tuple(ToonInfo(f"Toon {i}", "ttr", f"dna{i}", "cat", 10 + i,
                          played_at=played) for i in range(n))


# ── AccountInfo ─────────────────────────────────────────────────────────────

def test_title_prefers_the_label():
    assert AccountInfo("a", "ttr", "flossbud").title == "flossbud"
    assert AccountInfo("a", "ttr", "flossbud", label="Main").title == "Main"


def test_primary_is_the_starred_toon_else_the_most_recent():
    account = AccountInfo("a", "ttr", "u", toons=toons(3), primary_name="Toon 2")
    assert account.primary.name == "Toon 2"
    assert AccountInfo("a", "ttr", "u", toons=toons(3)).primary.name == "Toon 0"
    assert AccountInfo("a", "ttr", "u", toons=toons(3),
                       primary_name="Gone").primary.name == "Toon 0"
    assert AccountInfo("a", "ttr", "u").primary is None


def test_six_toons_are_shown_and_the_primary_is_always_among_them():
    eight = toons(8)
    account = AccountInfo("a", "ttr", "u", toons=eight)
    assert [t.name for t in account.shown_toons] == [f"Toon {i}" for i in range(6)]
    starred = AccountInfo("a", "ttr", "u", toons=eight, primary_name="Toon 7")
    names = [t.name for t in starred.shown_toons]
    assert len(names) == 6 and "Toon 7" in names
    assert names[:5] == [f"Toon {i}" for i in range(5)]


# ── Copy ────────────────────────────────────────────────────────────────────

def test_sheet_sub():
    assert m.sheet_sub(8) == "8 accounts · logins are kept in your system keyring"
    assert m.sheet_sub(1).startswith("1 account ·")
    assert "cannot be saved" in m.sheet_sub(2, keyring_available=False)


def test_card_and_toon_meta():
    assert m.card_meta(5) == "5 of 16 accounts"
    assert m.toons_meta(3) == "3 of 6"
    assert m.toons_meta(8) == "6 of 6"


def test_account_sub():
    assert m.account_sub(AccountInfo("a", "ttr", "u")) == (
        "No toons seen yet · launch once to discover them")
    account = AccountInfo("a", "ttr", "u", toons=toons(3), primary_name="Toon 1")
    assert m.account_sub(account) == "Toon 1 · 3 of 6 toons"
    assert m.account_sub(AccountInfo("a", "ttr", "u", toons=toons(8))) == (
        "Toon 0 · 6 of 6 toons")


@pytest.mark.parametrize("login, running, text", [
    (LOGIN_SAVED, False, "Login saved"), (LOGIN_NONE, False, "Asks at launch"),
    (LOGIN_FAILED, False, "Login failed"), (LOGIN_SAVED, True, "Running"),
    (LOGIN_FAILED, True, "Running"),
])
def test_status_text(login, running, text):
    assert m.status_text(AccountInfo("a", "ttr", "u", login=login, running=running)) == text


def test_login_row_copy_per_state():
    saved = AccountInfo("a", "ttr", "u", login=LOGIN_SAVED)
    failed = AccountInfo("a", "ttr", "u", login=LOGIN_FAILED)
    none = AccountInfo("a", "ttr", "u")
    assert m.login_line(saved) == "Password saved in your system keyring"
    assert m.login_line(failed) == "The last sign-in was rejected. Check the password."
    assert m.login_line(none) == "No saved login. You will be asked when you launch."
    assert m.login_buttons(saved) == ("Edit login", m.FORM_EDIT, True)
    assert m.login_buttons(failed) == ("Fix login", m.FORM_FIX, True)
    assert m.login_buttons(none) == ("Add login", m.FORM_ADD_LOGIN, False)


def test_form_titles_and_buttons():
    assert m.form_title(m.FORM_ADD_ACCOUNT, "ttr") == "Add a Toontown Rewritten account"
    assert m.form_title(m.FORM_ADD_ACCOUNT, "cc") == "Add a Corporate Clash account"
    assert m.form_title(m.FORM_FIX, "ttr") == "Fix login"
    assert m.form_primary_text(m.FORM_ADD_ACCOUNT) == "Add account"
    assert m.form_primary_text(m.FORM_EDIT) == "Save login"
    assert m.form_title(m.FORM_LAUNCH, "cc") == "Enter password to launch"
    assert m.form_primary_text(m.FORM_LAUNCH) == "Launch"
    assert m.add_account_text("ttr") == "Add TTR account"
    assert m.add_account_text("cc") == "Add CC account"


def test_toon_line():
    assert m.toon_line(ToonInfo("A", "ttr", species="duck", laff=96)) == "Duck · 96 laff"
    assert m.toon_line(ToonInfo("A", "cc", species="CAT")) == "Cat"
    assert m.toon_line(ToonInfo("A", "ttr", laff=5)) == "5 laff"
    assert m.toon_line(ToonInfo("A", "ttr")) == ""


@pytest.mark.parametrize("days, text", [
    (0, "played today"), (0.9, "played today"), (1, "played yesterday"),
    (4, "played 4d ago"), (13, "played 13d ago"), (14, "played 2w ago"),
    (59, "played 8w ago"), (61, "played 2mo ago"), (150, "played 5mo ago"),
    (400, "played 1y ago"),
])
def test_played_text(days, text):
    assert m.played_text(NOW - days * DAY, NOW) == text


def test_played_text_without_a_stamp_or_from_the_future():
    assert m.played_text(None, NOW) == ""
    assert m.played_text(NOW + 500, NOW) == "played today"


def test_toon_played_line():
    toon = ToonInfo("A", "ttr", played_at=NOW - DAY)
    assert m.toon_played_line(toon, True, NOW) == "Primary · played yesterday"
    assert m.toon_played_line(toon, False, NOW) == "played yesterday"
    assert m.toon_played_line(ToonInfo("A", "ttr"), True, NOW) == "Primary"
    assert m.toon_played_line(ToonInfo("A", "ttr"), False, NOW) == ""


def test_confirm_copy_names_the_account():
    account = AccountInfo("a", "ttr", "flossbud3", label="Alt")
    assert m.forget_question(account) == "Forget the saved login for flossbud3?"
    assert m.remove_question(account) == "Remove Alt from the launcher?"


# ── The in-memory backend ───────────────────────────────────────────────────

@pytest.fixture
def backend(qapp):
    backend = FakeAccountsBackend.demo(now=NOW)
    backend.events = []
    backend.changed.connect(lambda: backend.events.append("changed"))
    return backend


def test_demo_matches_the_design_render(backend):
    ttr, cc = backend.accounts("ttr"), backend.accounts("cc")
    assert [a.username for a in ttr] == [
        "flossbud", "flossbud27", "hirofloss", "crimsondeku", "flossbud3"]
    assert [a.username for a in cc] == ["flossbud", "clashmain", "fizz@example"]
    assert [m.status_text(a) for a in ttr][-1] == "Login failed"
    assert m.status_text(cc[1]) == "Running"
    assert m.account_sub(ttr[1]) == "Hector Pepperoni · 6 of 6 toons"
    assert m.account_sub(ttr[3]).startswith("No toons seen yet")
    assert backend.account("t5").failed_reason
    assert backend.account("nope") is None
    assert backend.keyring_available()


def test_add_account(backend):
    new_id = backend.add_account("cc", "newbie", "pw", True)
    assert backend.account(new_id).login == LOGIN_SAVED
    assert backend.accounts("cc")[-1].id == new_id
    assert backend.events == ["changed"]
    unsaved = backend.add_account("cc", "typed", "pw", False)
    assert backend.account(unsaved).login == LOGIN_NONE


def test_add_account_stops_at_the_ceiling(backend):
    for i in range(11):
        assert backend.add_account("ttr", f"u{i}", "pw", True)
    assert len(backend.accounts("ttr")) == 16
    assert backend.add_account("ttr", "one-too-many", "pw", True) is None


def test_save_login_clears_a_rejected_sign_in(backend):
    assert backend.save_login("t5", "flossbud3", "better", True) is True
    account = backend.account("t5")
    assert (account.login, account.failed_reason) == (LOGIN_SAVED, None)


def test_save_login_without_keeping_it_asks_at_launch(backend):
    backend.save_login("t1", "flossbud", "pw", False)
    assert backend.account("t1").login == LOGIN_NONE


def test_save_login_with_a_blank_password_keeps_the_state(backend):
    backend.save_login("t1", "renamed", "", True)
    account = backend.account("t1")
    assert (account.username, account.login) == ("renamed", LOGIN_SAVED)


def test_forget_label_remove_and_primary(backend):
    backend.forget_login("t5")
    assert backend.account("t5").login == LOGIN_NONE
    backend.set_label("t1", "Main")
    assert backend.account("t1").title == "Main"
    backend.set_primary("t2", "Zippy McMuffin")
    assert backend.account("t2").primary.name == "Zippy McMuffin"
    backend.set_primary("t2", "Not A Toon")
    assert backend.account("t2").primary.name == "Zippy McMuffin"
    backend.remove_account("t4")
    assert backend.account("t4") is None
    assert [c[0] for c in backend.calls] == [
        "forget_login", "set_label", "set_primary", "set_primary", "remove_account"]


def test_a_write_that_changes_nothing_is_silent(backend):
    backend.set_label("t1", "")
    backend.set_primary("t2", "Hector Pepperoni")
    backend.remove_account("gone")
    assert backend.events == []


def test_without_a_keyring_nothing_is_saved(backend):
    backend.set_keyring_available(False)
    new_id = backend.add_account("ttr", "u", "pw", True)
    assert backend.account(new_id).login == LOGIN_NONE


def test_launching_with_a_typed_password(backend):
    backend.forget_login("t1")
    assert backend.launch_with_password("t1", "pw", True) is True
    account = backend.account("t1")
    assert account.running and account.login == LOGIN_SAVED
    backend.forget_login("t3")
    assert backend.launch_with_password("t3", "pw", False) is True
    assert backend.account("t3").running and backend.account("t3").login == LOGIN_NONE
    assert backend.launch_with_password("t3", "", True) is False
    assert backend.launch_with_password("nope", "pw", True) is False
