"""The Accounts sheet on the real launcher: the backend over LaunchTab and
CredentialsManager, the routes into the sheet, and asking for a password at
launch. The keyring is an in-process one, so "nothing was written to the
keyring" is something a test can look at.

Construction checks: real window, real launcher, offscreen; no game is
started (the launcher's workers are stand-ins).
"""

import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.test_launchpad_window import _dispose, isolated  # noqa: F401
from utils.widgets.launchpad import accounts_model as m
from utils.widgets.launchpad.header import SHEET_ACCOUNTS, SHEET_SETTINGS


class FakeWorker:
    def __init__(self, log, account_id):
        self._log, self._account_id = log, account_id

    def login(self, username, password):
        self._log.append(("login", self._account_id, username, password))

    def login_with_token(self, token):
        self._log.append(("token", self._account_id, token))

    def register_and_login(self, username, password, label=""):
        self._log.append(("register", self._account_id, username, password))

    def cancel(self):
        pass

    class _Signal:
        def connect(self, _slot):
            pass

    launcher_token_obtained = _Signal()


class FakeLauncher:
    def is_running(self):
        return False

    def kill(self):
        pass


@pytest.fixture
def stage(isolated, monkeypatch, qapp, tmp_path):
    """The launchpad window with a working in-process keyring and a launcher
    whose workers only record what they were asked to do."""
    import keyring
    import keyring.core
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 999

        def __init__(self):
            self.store = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    backend = MemoryKeyring()
    previous = keyring.core._keyring_backend
    keyring.set_keyring(backend)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)

    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    win.resize(880, 860)
    win.show()
    tab = win.launch_tab
    creds = tab.cred_manager
    creds._probe_complete = True
    creds._use_keyring = True
    # An empty read makes the manager look through every other keyring
    # backend on the machine (seconds, headless). Not what is under test.
    monkeypatch.setattr(creds, "_recover_password_from_compatible_backends",
                        lambda account_id: "")
    tab._grandstand_credential_kind = "ok"

    # No game is started: every launch stops at the worker.
    win.launches = []
    win.failures = []

    def fake_launchers(game, account_id):
        slot = tab._slots[game][account_id]
        slot.worker = FakeWorker(win.launches, account_id)
        slot.launcher = FakeLauncher()
        return slot.worker, slot.launcher

    # A game "install": the files the launcher checks for before signing in.
    # (Real files, not a patched os.path.isfile: that function is the whole
    # process's, and everything else that asks it would be lied to.)
    import tabs.launch_tab as launch_tab_module
    engine = tmp_path / "engine"
    engine.mkdir()
    for binary in (launch_tab_module.engine_binary_path(str(engine)),
                   os.path.join(str(engine),
                                launch_tab_module.get_cc_engine_executable_name())):
        os.makedirs(os.path.dirname(binary), exist_ok=True)
        open(binary, "w").close()
    monkeypatch.setattr(tab, "_make_launchers", fake_launchers)
    monkeypatch.setattr(tab, "_get_engine_dir", lambda game: str(engine))
    monkeypatch.setattr(tab, "_cc_gate_ok", lambda game, account_id: True)
    monkeypatch.setattr(tab, "_show_failure_dialog",
                        lambda game, account_id, msg: win.failures.append((account_id, msg)))

    win.keyring = backend
    qapp.processEvents()
    # Most tests read the backend directly, as the open sheet would.
    win.accounts_backend.set_active(True)
    yield win
    _dispose(win, qapp)
    keyring.core._keyring_backend = previous


def add(win, game, username, password="pw", label=""):
    creds = win.launch_tab.cred_manager
    before = {a.id for a in creds.get_accounts_metadata(game)}
    assert creds.add_account(label=label, username=username, password=password, game=game)
    win.launch_tab._reconcile_slots()
    win.launch_tab._render_current_view(game)
    return next(a.id for a in creds.get_accounts_metadata(game) if a.id not in before)


def stored_passwords(win):
    return sorted(v for v in win.keyring.store.values() if v)


def click(widget):
    QTest.mouseClick(widget, Qt.LeftButton)


# ── Mounted ────────────────────────────────────────────────────────────────

def test_the_accounts_button_opens_the_real_sheet_on_its_list(stage):
    from utils.widgets.launchpad.accounts_sheet import AccountsSheet
    add(stage, "ttr", "flossbud")
    stage.header.buttons.buttons[SHEET_ACCOUNTS].click()
    sheet = stage.sheet_host.current_content()
    assert isinstance(sheet, AccountsSheet) and sheet is stage.accounts_sheet
    head = stage.sheet_host.panel.header
    assert head.title_label.text() == "Accounts"
    assert head.sub_label.text() == "1 account · logins are kept in your system keyring"
    assert head.back_button.isHidden()
    assert [r.title_text() for r in sheet.rows.values()] == ["flossbud"]


def test_the_button_always_opens_the_list_even_after_an_account_page(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.open_account(account_id)
    assert stage.accounts_sheet.account_id() == account_id
    assert not stage.sheet_host.panel.header.back_button.isHidden()
    stage.open_sheet(None)
    stage.header.buttons.buttons[SHEET_ACCOUNTS].click()
    assert stage.accounts_sheet.account_id() is None


def test_another_sheet_does_not_inherit_the_back_button(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.open_account(account_id)
    stage.open_sheet(SHEET_SETTINGS)
    assert stage.sheet_host.panel.header.back_button.isHidden()
    assert stage.sheet_host.panel.header.title_label.text() == "Settings"


# ── The backend reads ──────────────────────────────────────────────────────

def test_accounts_come_from_the_launcher_in_its_order(stage):
    first = add(stage, "ttr", "flossbud", label="Main")
    second = add(stage, "ttr", "alt", password="")
    clash = add(stage, "cc", "clashmain")
    backend = stage.accounts_backend
    ttr = backend.accounts("ttr")
    assert [(a.id, a.title, a.username, a.login) for a in ttr] == [
        (first, "Main", "flossbud", m.LOGIN_SAVED),
        (second, "alt", "alt", m.LOGIN_NONE)]
    assert [a.id for a in backend.accounts("cc")] == [clash]
    assert backend.keyring_available() is True
    assert backend.account(clash).game == "cc"


def test_a_rejected_sign_in_reads_failed_with_the_servers_words(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.launch_tab.cred_manager.set_login_failed(account_id, True, "Wrong password.")
    account = stage.accounts_backend.account(account_id)
    assert (account.login, account.failed_reason) == (m.LOGIN_FAILED, "Wrong password.")


def test_running_and_toons_come_from_the_launcher(stage):
    from services.ttr_login_service import LoginState
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud")
    tab._recent_toons.record(account_id, "Hector", "ttr", dna="aa", laff=40, species="DOG")
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb", laff=137)
    tab._recent_toons.set_primary(account_id, "Hector")
    tab._slots["ttr"][account_id].state = LoginState.LOADING
    account = stage.accounts_backend.account(account_id)
    assert not account.running                       # loading is not running yet
    assert [t.name for t in account.toons] == ["Flossbud", "Hector"]
    assert account.primary.name == "Hector"
    assert account.toons[1].species == "DOG" and account.toons[1].played_at is not None
    tab._slots["ttr"][account_id].launcher = type(
        "Live", (), {"is_running": lambda self: True, "kill": lambda self: None})()
    assert stage.accounts_backend.account(account_id).running


def test_looks_come_from_the_shared_store(stage):
    stage.session.customizations.set("ttr", "Flossbud", {"accent": "#e74a4a"})
    assert stage.accounts_backend.look_entry("ttr", "Flossbud") == {"accent": "#e74a4a"}
    assert stage.accounts_backend.look_entry("ttr", "Nobody") == {}


def test_the_keyring_is_asked_once_per_account_until_something_changes(stage, monkeypatch):
    first = add(stage, "ttr", "one")
    add(stage, "ttr", "two")
    creds = stage.launch_tab.cred_manager
    calls = []
    original = creds.login_status
    monkeypatch.setattr(creds, "login_status",
                        lambda account_id: calls.append(account_id) or original(account_id))
    backend = stage.accounts_backend
    backend._login_cache.clear()
    for _ in range(3):
        backend.accounts("ttr")
    assert len(calls) == 2
    backend.set_label(first, "Renamed")              # a write: that account again
    backend.accounts("ttr")
    assert calls.count(first) == 2 and len(calls) == 3


def test_the_sheet_follows_the_launcher(stage):
    stage.open_list()
    seen = []
    stage.accounts_backend.changed.connect(lambda: seen.append(1))
    account_id = add(stage, "cc", "clashmain")
    assert seen and account_id in stage.accounts_sheet.rows
    count = len(seen)
    stage.launch_tab._render_current_view("cc")      # a re-render, nothing new
    assert len(seen) == count


def test_nothing_is_read_from_the_keyring_while_the_sheet_is_closed(stage, monkeypatch):
    creds = stage.launch_tab.cred_manager
    reads = []
    original = creds.login_status
    monkeypatch.setattr(creds, "login_status",
                        lambda account_id: reads.append(account_id) or original(account_id))
    seen = []
    stage.accounts_backend.changed.connect(lambda: seen.append(1))
    stage.accounts_backend.set_active(False)        # the sheet is closed
    first = add(stage, "ttr", "one")
    second = add(stage, "ttr", "two")
    stage.launch_tab._render_current_view("ttr")
    assert reads == [] and seen == []               # launcher changes, sheet closed
    stage.open_list()                               # now someone is looking
    assert sorted(reads) == sorted([first, second])
    assert set(stage.accounts_sheet.rows) == {first, second}
    stage.open_sheet(None)
    stage.sheet_host.hide()                          # as the close animation ends
    reads.clear()
    add(stage, "ttr", "three")
    assert reads == []


# ── The backend writes ─────────────────────────────────────────────────────

def test_adding_an_account_from_the_sheet(stage):
    stage.open_add("ttr")
    form = stage.accounts_sheet.add_form()
    assert form is not None and form.game() == "ttr"
    form.username.setText("newbie")
    form.password.setText("s3cret")
    click(form.submit_button)
    accounts = stage.launch_tab.cred_manager.get_accounts("ttr")
    assert [(a.username, a.password) for a in accounts] == [("newbie", "s3cret")]
    assert stored_passwords(stage) == ["s3cret"]
    assert [a.label for a in stage.launcher_port.accounts()] == ["newbie"]
    row = next(iter(stage.accounts_sheet.rows.values()))
    assert row.status_text() == "Login saved"


def test_adding_an_account_without_keeping_its_login_stores_nothing(stage):
    stage.open_add("ttr")
    form = stage.accounts_sheet.add_form()
    form.username.setText("newbie")
    form.password.setText("s3cret")
    form.keep_toggle.setChecked(False)
    click(form.submit_button)
    assert stored_passwords(stage) == []
    account = stage.accounts_backend.accounts("ttr")[0]
    assert (account.username, account.login) == ("newbie", m.LOGIN_NONE)
    assert next(iter(stage.accounts_sheet.rows.values())).status_text() == "Asks at launch"


def test_saving_a_login_and_keeping_the_stored_one_on_a_blank_password(stage):
    account_id = add(stage, "ttr", "flossbud", password="old")
    backend = stage.accounts_backend
    assert backend.save_login(account_id, "renamed", "", True) is True
    assert stored_passwords(stage) == ["old"]
    assert backend.account(account_id).username == "renamed"
    backend.save_login(account_id, "renamed", "new", True)
    assert stored_passwords(stage) == ["new"]


def test_saving_a_login_with_keep_off_removes_the_stored_one(stage):
    account_id = add(stage, "ttr", "flossbud", password="old")
    stage.accounts_backend.save_login(account_id, "flossbud", "typed", False)
    assert stored_passwords(stage) == []
    assert stage.accounts_backend.account(account_id).login == m.LOGIN_NONE


def test_a_new_password_clears_a_rejected_sign_in(stage):
    account_id = add(stage, "ttr", "flossbud", password="wrong")
    stage.launch_tab.cred_manager.set_login_failed(account_id, True, "Nope.")
    stage.accounts_backend.save_login(account_id, "flossbud", "right", True)
    assert stage.accounts_backend.account(account_id).login == m.LOGIN_SAVED


def test_forgetting_a_login(stage):
    account_id = add(stage, "ttr", "flossbud", password="old")
    clash = add(stage, "cc", "clashmain", password="")
    stage.launch_tab.cred_manager.set_launcher_token(clash, "token-123")
    backend = stage.accounts_backend
    # A sign-in stores its token mid-launch and the launch state then moves,
    # which is what makes the backend ask again; here it is set directly.
    backend._login_cache.clear()
    assert backend.account(clash).login == m.LOGIN_SAVED       # by its token
    backend.forget_login(account_id)
    backend.forget_login(clash)
    assert stored_passwords(stage) == []
    assert backend.account(account_id).login == m.LOGIN_NONE
    assert backend.account(clash).login == m.LOGIN_NONE
    assert stage.launch_tab.cred_manager.get_launcher_token(clash) == ""


def test_the_label_reaches_the_launcher_card(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.accounts_backend.set_label(account_id, "Gag grind alt")
    assert stage.launcher_port.accounts()[0].label == "Gag grind alt"
    assert stage.launch_tab.grandstand.entry_for("ttr", account_id) is not None


def test_removing_an_account_asks_nothing_more(stage, monkeypatch):
    def no_dialog(*args, **kwargs):
        raise AssertionError("the sheet has already asked")

    monkeypatch.setattr("tabs.launch_tab.ConfirmDialog", no_dialog)
    account_id = add(stage, "ttr", "flossbud", password="pw")
    stage.accounts_backend.remove_account(account_id)
    assert stage.launch_tab.cred_manager.get_accounts_metadata("ttr") == []
    assert stored_passwords(stage) == []
    assert stage.launcher_port.accounts() == []


def test_the_star_sets_the_launchers_primary_toon(stage):
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud")
    tab._recent_toons.record(account_id, "Hector", "ttr", dna="aa")
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb")
    stage.accounts_backend.set_primary(account_id, "Hector")
    assert tab._recent_toons.primary_name(account_id) == "Hector"
    assert stage.accounts_backend.account(account_id).primary.name == "Hector"


def test_a_newly_discovered_toon_shows_up(stage):
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud")
    tab._toon_bridge.register_launch(1234, account_id, "ttr") \
        if hasattr(tab._toon_bridge, "register_launch") else None
    seen = []
    stage.accounts_backend.changed.connect(lambda: seen.append(1))
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb")
    tab._render_current_view("ttr")
    assert seen
    assert [t.name for t in stage.accounts_backend.account(account_id).toons] == ["Flossbud"]


# ── Routes from the launcher ───────────────────────────────────────────────

def test_the_launchers_link_reads_accounts_and_opens_the_list(stage):
    add(stage, "ttr", "flossbud")
    link = stage.launch_tab.grandstand.shelf.manage_link
    assert link.text() == "Accounts"
    stage.launch_tab.grandstand.manage_requested.emit("ttr")
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.account_id() is None


def test_the_link_survives_the_launcher_rebuilding_itself(stage):
    stage.launch_tab._rebuild_sections_container() \
        if hasattr(stage.launch_tab, "_rebuild_sections_container") else None
    stage.launch_tab._apply_accounts_router()
    assert stage.launch_tab.grandstand.shelf.manage_link.text() == "Accounts"


def test_a_cards_gear_opens_that_account(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.launch_tab.grandstand.edit_requested.emit("ttr", account_id, "account")
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.account_id() == account_id
    assert stage.accounts_sheet.login_form() is None
    assert not stage.launch_tab.grandstand.in_focus_mode()     # not the old page


def test_the_gear_on_a_rejected_login_opens_fix_login(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.launch_tab.cred_manager.set_login_failed(account_id, True)
    stage.open_account(account_id)
    assert stage.accounts_sheet.login_form().mode() == m.FORM_FIX


def test_add_account_opens_the_add_form_for_the_active_game(stage):
    stage.launch_tab.grandstand._party.set_active_game("cc")
    stage.launch_tab.grandstand.add_account_requested.emit("cc")
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.add_form().game() == "cc"
    assert not stage.launch_tab.grandstand.in_focus_mode()


def test_without_a_router_the_launcher_keeps_its_own_pages(stage, monkeypatch):
    account_id = add(stage, "ttr", "flossbud")
    tab = stage.launch_tab
    tab.set_accounts_router(None)
    assert tab.grandstand.shelf.manage_link.text() == "Manage"
    opened = []
    monkeypatch.setattr(tab, "_open_account_sheet", lambda g, a: opened.append(a))
    monkeypatch.setattr(tab, "_on_reorder", lambda g: opened.append("reorder"))
    tab.grandstand.edit_requested.emit("ttr", account_id, "account")
    tab.grandstand.manage_requested.emit("ttr")
    assert opened == [account_id, "reorder"]
    assert stage.open_sheet_name() is None


# ── A password asked for at launch ─────────────────────────────────────────

def test_launching_an_account_with_a_login_just_launches(stage):
    account_id = add(stage, "ttr", "flossbud", password="pw")
    stage.launch_tab.launch_account("ttr", account_id)
    assert stage.launches == [("login", account_id, "flossbud", "pw")]
    assert stage.open_sheet_name() is None and stage.failures == []


def test_launching_without_a_login_asks_instead_of_failing(stage):
    from services.ttr_login_service import LoginState
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.hide()
    stage.launch_tab.launch_account("ttr", account_id)
    assert stage.launches == [] and stage.failures == []
    assert stage.isVisible()
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    form = stage.accounts_sheet.login_form()
    assert form.mode() == m.FORM_LAUNCH
    assert form.title_label.text() == "Enter password to launch"
    assert form.username.text() == "flossbud" and form.username.isReadOnly()
    assert form.keep_toggle.isChecked()
    assert stage.launch_tab._slots["ttr"][account_id].state != LoginState.FAILED


def test_launch_and_keep_saves_the_login_then_launches(stage, qapp):
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.launch_tab.launch_account("ttr", account_id)
    form = stage.accounts_sheet.login_form()
    form.password.setText("typed")
    click(form.submit_button)
    assert stage.launches == [("login", account_id, "flossbud", "typed")]
    assert stored_passwords(stage) == ["typed"]
    assert stage.accounts_backend.account(account_id).login == m.LOGIN_SAVED
    qapp.processEvents()
    assert stage.open_sheet_name() is None           # back on the launcher


def test_launch_for_this_launch_only_writes_nothing(stage, qapp):
    account_id = add(stage, "ttr", "flossbud", password="")
    creds = stage.launch_tab.cred_manager
    before = dict(stage.keyring.store)
    stage.launch_tab.launch_account("ttr", account_id)
    form = stage.accounts_sheet.login_form()
    form.password.setText("typed")
    form.keep_toggle.setChecked(False)
    click(form.submit_button)
    assert stage.launches == [("login", account_id, "flossbud", "typed")]
    assert stage.keyring.store == before             # nothing written to the keyring
    assert not creds.has_session_password(account_id)     # and not kept in memory
    assert creds.login_status(account_id) == "none"
    assert stage.accounts_backend.account(account_id).login == m.LOGIN_NONE
    assert account_id not in stage.launch_tab._one_time_logins


def test_cancel_leaves_the_account_idle(stage):
    from services.ttr_login_service import LoginState
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.launch_tab.launch_account("ttr", account_id)
    click(stage.accounts_sheet.login_form().cancel_button)
    assert stage.launches == [] and stage.failures == []
    assert stage._login_requests == []
    assert stage.launch_tab._slots["ttr"][account_id].state == LoginState.IDLE
    assert stored_passwords(stage) == []


def test_closing_the_sheet_on_the_question_is_a_cancel(stage):
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.launch_tab.launch_account("ttr", account_id)
    stage.sheet_host.close()
    assert stage.accounts_sheet.launch_login_account() is None
    assert stage._login_requests == [] and stage.launches == []


def test_a_party_asks_one_after_another_and_launches_the_rest_meanwhile(stage, qapp):
    first = add(stage, "ttr", "no-login-1", password="")
    saved = add(stage, "ttr", "has-login", password="pw")
    second = add(stage, "ttr", "no-login-2", password="")
    for account_id in (first, saved, second):       # the party, in order
        stage.launch_tab.launch_account("ttr", account_id)
    assert stage.launches == [("login", saved, "has-login", "pw")]
    assert stage._login_requests == [first, second]
    assert stage.accounts_sheet.launch_login_account() == first

    form = stage.accounts_sheet.login_form()
    form.password.setText("one")
    click(form.submit_button)
    qapp.processEvents()
    assert stage.accounts_sheet.launch_login_account() == second
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.login_form().username.text() == "no-login-2"

    click(stage.accounts_sheet.login_form().cancel_button)       # skip this one
    qapp.processEvents()
    assert stage._login_requests == []
    assert [entry[1] for entry in stage.launches] == [saved, first]


def test_launching_the_same_account_twice_asks_once(stage):
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.launch_tab.launch_account("ttr", account_id)
    stage.launch_tab.launch_account("ttr", account_id)
    assert stage._login_requests == [account_id]


def test_corporate_clash_without_token_or_password_asks_too(stage):
    account_id = add(stage, "cc", "clashmain", password="")
    stage.launch_tab.launch_account("cc", account_id)
    assert stage.launches == [] and stage.failures == []
    assert stage.accounts_sheet.login_form().mode() == m.FORM_LAUNCH


def test_a_clash_launch_for_this_launch_only_does_not_keep_its_token(stage):
    tab = stage.launch_tab
    account_id = add(stage, "cc", "clashmain", password="")
    tab.launch_account_once("cc", account_id, "typed")
    assert stage.launches == [("register", account_id, "clashmain", "typed")]
    assert account_id in tab._one_time_logins        # a sign-in is under way
    worker = tab._slots["cc"][account_id].worker
    tab._on_token_obtained("cc", account_id, worker, "earned-token")
    assert tab.cred_manager.get_launcher_token(account_id) == ""
    assert stage.keyring.store == {} or not any(stage.keyring.store.values())
    assert account_id not in tab._one_time_logins


def test_a_normal_clash_sign_in_still_keeps_its_token(stage):
    tab = stage.launch_tab
    account_id = add(stage, "cc", "clashmain", password="pw")
    tab.launch_account("cc", account_id)
    worker = tab._slots["cc"][account_id].worker
    tab._on_token_obtained("cc", account_id, worker, "earned-token")
    assert tab.cred_manager.get_launcher_token(account_id) == "earned-token"


def test_without_a_router_a_missing_login_fails_as_it_always_did(stage):
    account_id = add(stage, "ttr", "flossbud", password="")
    stage.launch_tab.set_accounts_router(None)
    stage.launch_tab.launch_account("ttr", account_id)
    assert stage.failures == [(account_id, "Missing username or password. Click Edit.")]
    assert stage.open_sheet_name() is None


# ── Looks from an account page ─────────────────────────────────────────────

def test_a_slots_pencil_opens_that_toon_and_closing_returns_to_the_account(stage, qapp):
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud")
    tab._recent_toons.record(account_id, "Hector", "ttr", dna="aa")
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb")
    tab._render_current_view("ttr")
    stage.open_account(account_id)
    slot = next(s for s in stage.accounts_sheet.slots if s.name_text() == "Hector")
    click(slot.pencil)
    assert stage.open_sheet_name() is None           # the editor is in the launcher
    assert tab.grandstand.in_focus_mode()
    draft = tab.grandstand.appearance_sheet.draft() \
        if callable(getattr(tab.grandstand.appearance_sheet, "draft", None)) else None
    if draft is not None:
        assert draft.toon_name == "Hector"
    tab.grandstand.close_sheet()
    qapp.processEvents()
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.account_id() == account_id


def test_closing_an_editor_opened_from_a_card_goes_nowhere(stage, qapp):
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud")
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb")
    tab._render_current_view("ttr")
    tab._open_appearance_sheet("ttr", account_id)
    tab.grandstand.close_sheet()
    qapp.processEvents()
    assert stage.open_sheet_name() is None


def test_a_launch_state_change_makes_the_backend_ask_the_keyring_again(stage):
    """A first Corporate Clash sign-in earns a token mid-launch: once the
    launch state moves, the account must read as saved."""
    from services.ttr_login_service import LoginState
    tab = stage.launch_tab
    clash = add(stage, "cc", "clashmain", password="")
    backend = stage.accounts_backend
    assert backend.account(clash).login == m.LOGIN_NONE
    tab.cred_manager.set_launcher_token(clash, "earned")
    assert backend.account(clash).login == m.LOGIN_NONE        # still the cached answer
    tab._slots["cc"][clash].state = LoginState.LAUNCHING
    tab._render_current_view("cc")
    assert backend.account(clash).login == m.LOGIN_SAVED


# ── The launcher card of a rejected sign-in ────────────────────────────────

def _card(stage, account_id):
    return stage.launch_tab.grandstand.shelf.card_for(account_id)


def _reject(stage, game, account_id, reason="Incorrect password."):
    stage.launch_tab.cred_manager.set_login_failed(account_id, True, reason)
    stage.launch_tab._render_current_view(game)


def test_a_rejected_sign_in_turns_the_card_into_a_fix_login_card(stage, qapp):
    account_id = add(stage, "ttr", "flossbud")
    card = _card(stage, account_id)
    assert not card.shows_fix_login() and card.fix_pill.isHidden()
    _reject(stage, "ttr", account_id)
    card = _card(stage, account_id)
    qapp.processEvents()
    assert card.shows_fix_login()
    assert card.fix_pill.isVisibleTo(card) and card.fix_pill.text() == "Fix login"
    assert card.fix_pill.height() == 22
    assert not card.footer.isVisibleTo(card)              # the pill replaces it
    assert not card.action.isVisibleTo(card)              # no Launch / Retry on it
    assert card.rect().contains(card.fix_pill.geometry())


def test_the_fix_login_pill_opens_the_account_on_its_login_form(stage):
    account_id = add(stage, "ttr", "flossbud")
    _reject(stage, "ttr", account_id)
    click(_card(stage, account_id).fix_pill)
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.account_id() == account_id
    assert stage.accounts_sheet.login_form().mode() == m.FORM_FIX
    assert stage.accounts_sheet.reason_label is not None


def test_pressing_a_failed_card_opens_fix_login_and_does_not_stage_it(stage):
    account_id = add(stage, "ttr", "flossbud")
    _reject(stage, "ttr", account_id)
    party = stage.launch_tab._party
    stage.launch_tab.grandstand._on_card_clicked(account_id)
    assert not party.is_selected("ttr", account_id)
    assert stage.accounts_sheet.login_form().mode() == m.FORM_FIX


def test_a_failed_account_is_not_left_selected_for_launch(stage):
    good = add(stage, "ttr", "good")
    bad = add(stage, "ttr", "bad")
    party = stage.launch_tab._party
    party.toggle("ttr", good)
    party.toggle("ttr", bad)
    _reject(stage, "ttr", bad)
    assert party.selected("ttr") == [good]


def test_fixing_the_login_gives_the_card_back(stage, qapp):
    account_id = add(stage, "ttr", "flossbud", password="wrong")
    _reject(stage, "ttr", account_id)
    stage.accounts_backend.save_login(account_id, "flossbud", "right", True)
    qapp.processEvents()
    card = _card(stage, account_id)
    assert not card.shows_fix_login() and not card.fix_pill.isVisibleTo(card)
    stage.launch_tab.grandstand._on_card_clicked(account_id)
    assert stage.launch_tab._party.is_selected("ttr", account_id)


def test_a_running_account_shows_running_not_the_pill(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.launch_tab.cred_manager.set_login_failed(account_id, True)
    stage.launch_tab._slots["ttr"][account_id].launcher = type(
        "Live", (), {"is_running": lambda self: True, "kill": lambda self: None})()
    stage.launch_tab._render_current_view("ttr")
    card = _card(stage, account_id)
    assert not card.shows_fix_login() and card.footer_text() == "Running"


def test_without_an_accounts_sheet_there_is_no_fix_login_card(stage):
    account_id = add(stage, "ttr", "flossbud")
    stage.launch_tab.cred_manager.set_login_failed(account_id, True)
    stage.launch_tab.set_accounts_router(None)
    card = _card(stage, account_id)
    assert not card.shows_fix_login() and card.fix_pill.isHidden()


def test_the_failed_card_is_drawn_with_a_red_border(stage, qapp):
    from PySide6.QtGui import QColor
    account_id = add(stage, "ttr", "flossbud")
    stage.resize(880, 860)
    qapp.processEvents()

    def border_colour():
        card = _card(stage, account_id)
        origin = card.mapTo(stage, card.rect().topLeft())
        image = stage.grab().toImage()
        return image.pixelColor(origin.x() + card.width() // 2, origin.y())

    plain = border_colour()
    _reject(stage, "ttr", account_id)
    qapp.processEvents()
    failed = border_colour()
    from utils.widgets.grandstand import palette
    red = QColor(palette.fix_login(stage._is_dark())["card_border"])
    distance = (abs(failed.red() - red.red()) + abs(failed.green() - red.green())
                + abs(failed.blue() - red.blue()))
    assert distance < 90, failed.name()
    assert failed.red() - failed.blue() > 60 and plain.red() - plain.blue() < 60


# ── The Appearance editor's contract with an Accounts sheet ────────────────

def _two_toons(stage):
    tab = stage.launch_tab
    account_id = add(stage, "ttr", "flossbud", label="Main")
    tab._recent_toons.record(account_id, "Hector", "ttr", dna="aa")
    tab._recent_toons.record(account_id, "Flossbud", "ttr", dna="bb")
    tab._recent_toons.set_primary(account_id, "Flossbud")
    tab._render_current_view("ttr")
    return account_id


def test_the_editor_has_no_account_settings_link(stage):
    account_id = _two_toons(stage)
    stage.launch_tab._open_appearance_sheet("ttr", account_id)
    header = stage.launch_tab.grandstand.sheet.header
    assert header.cross_link_text() == ""
    assert not header.cross_link.isVisibleTo(header)


def test_the_toon_switcher_only_retargets_the_editor(stage):
    tab = stage.launch_tab
    account_id = _two_toons(stage)
    tab._open_appearance_sheet("ttr", account_id)
    editor = tab.grandstand.appearance_sheet
    assert editor.draft().toon_name == "Flossbud"
    tab.grandstand.subject_toon_chosen.emit("ttr", account_id, "Hector")
    assert editor.draft().toon_name == "Hector"                      # re-targeted
    assert tab._recent_toons.primary_name(account_id) == "Flossbud"  # untouched
    assert tab.grandstand.entry_for("ttr", account_id).toon_name == "Flossbud"


def test_the_switcher_says_what_it_does(stage, qapp):
    from utils.widgets.grandstand.appearance_controls import SWITCHER_NOTE_RETARGET
    tab = stage.launch_tab
    account_id = _two_toons(stage)
    tab._open_appearance_sheet("ttr", account_id)
    editor = tab.grandstand.appearance_sheet
    editor._on_pill_clicked()
    assert editor.switcher.heading_text() == "2 of 6 toons on Main"
    assert editor.switcher.note.text() == SWITCHER_NOTE_RETARGET == (
        "Pick a toon to edit its look. The primary toon is set with the star "
        "in Accounts.")
    assert editor.pill.toolTip() == "Edit another toon's look"
    editor._close_popovers()


def test_a_look_saved_for_a_named_toon_goes_under_that_toons_key(stage):
    tab = stage.launch_tab
    account_id = _two_toons(stage)
    assert tab.open_appearance_for_toon("ttr", "Hector", account_id) is True
    draft = tab.grandstand.appearance_sheet.draft()
    assert draft.toon_name == "Hector" and draft.game == "ttr"


def test_without_an_accounts_sheet_the_editor_is_as_it_was(stage):
    from utils.widgets.grandstand import appearance_sheet as appearance
    from utils.widgets.grandstand.appearance_controls import SWITCHER_NOTE
    tab = stage.launch_tab
    account_id = _two_toons(stage)
    tab.set_accounts_router(None)
    tab._open_appearance_sheet("ttr", account_id)
    editor = tab.grandstand.appearance_sheet
    assert tab.grandstand.sheet.header.cross_link_text() == appearance.CROSS_LINK
    editor._on_pill_clicked()
    assert editor.switcher.heading_text() == "2 toons on Main"
    assert editor.switcher.note.text() == SWITCHER_NOTE
    editor._close_popovers()
    tab.grandstand.subject_toon_chosen.emit("ttr", account_id, "Hector")
    assert tab._recent_toons.primary_name(account_id) == "Hector"    # the old write
