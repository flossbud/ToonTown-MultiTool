"""The Accounts sheet, on the in-memory backend, mounted in the sheet host
inside an 880x860 stand-in window (where it lives)."""

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from utils.widgets.launchpad import accounts_model as m
from utils.widgets.launchpad.accounts_backend import FakeAccountsBackend
from utils.widgets.launchpad.accounts_parts import (
    AccountRow, ConfirmRow, LoginForm, LoginRow, ToonSlot,
)
from utils.widgets.launchpad.accounts_sheet import AccountsSheet
from utils.widgets.launchpad.slide_sheet import SlideSheetHost

NOW = 2_000_000_000.0


class Stage:
    def __init__(self, qapp, is_dark=True, backend=None):
        self.qapp = qapp
        self.window = QWidget()
        self.window.resize(880, 860)
        self.window.setStyleSheet(
            f"QWidget {{ background: {'#1a1a1a' if is_dark else '#f4f6f8'}; }}")
        self.host = SlideSheetHost(self.window, top=112, is_dark=is_dark)
        self.backend = backend or FakeAccountsBackend.demo(now=NOW)
        self.sheet = AccountsSheet(self.backend, is_dark=is_dark, clock=lambda: NOW)
        self.window.show()
        self.host.open(self.sheet, self.sheet.IDENTITY, self.sheet.title(),
                       self.sheet.sub())
        self.sheet.attach_host(self.host)
        self.settle()

    def settle(self, seconds=0.45):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.qapp.processEvents()
            time.sleep(0.01)

    def header(self):
        head = self.host.panel.header
        return head.title_label.text(), head.sub_label.text()

    def back_visible(self):
        return not self.host.panel.header.back_button.isHidden()

    def close(self):
        self.window.close()
        self.window.deleteLater()


@pytest.fixture
def stage(qapp):
    stage = Stage(qapp)
    yield stage
    stage.close()


def click(widget):
    QTest.mouseClick(widget, Qt.LeftButton)


# ── The list ───────────────────────────────────────────────────────────────

def test_header_counts_every_account(stage):
    assert stage.header() == (
        "Accounts", "8 accounts · logins are kept in your system keyring")
    assert not stage.back_visible()
    assert stage.sheet.account_id() is None


def test_one_card_per_game_with_its_accounts_in_order(stage):
    sheet = stage.sheet
    assert list(sheet.cards) == ["ttr", "cc"]
    assert sheet.cards["ttr"].title_label.text() == "Toontown Rewritten"
    assert sheet.cards["ttr"].meta_label.text() == "5 of 16 accounts"
    assert sheet.cards["cc"].meta_label.text() == "3 of 16 accounts"
    ttr_rows = [w for w in sheet.cards["ttr"].rows() if isinstance(w, AccountRow)]
    assert [r.title_text() for r in ttr_rows] == [
        "flossbud", "flossbud27", "hirofloss", "crimsondeku", "flossbud3"]
    assert not sheet.cards["ttr"].logo.pixmap().isNull()


def test_rows_say_what_the_design_says(stage):
    rows = stage.sheet.rows
    assert rows["t2"].sub_text() == "Hector Pepperoni · 6 of 6 toons"
    assert rows["t4"].sub_text() == "No toons seen yet · launch once to discover them"
    assert rows["t4"].disc.toon() is None                 # the dashed empty circle
    assert rows["t1"].status_text() == "Login saved"
    assert rows["c2"].status_text() == "Running"
    assert rows["t5"].status_text() == "Login failed"
    assert rows["t5"].is_failed() and rows["t5"].fix_button is not None
    assert rows["t1"].fix_button is None
    assert rows["t2"].disc.toon().name == "Hector Pepperoni"


def test_a_running_account_with_a_rejected_login_just_reads_running(qapp):
    backend = FakeAccountsBackend.demo(now=NOW)
    backend.update("t5", running=True)
    stage = Stage(qapp, backend=backend)
    try:
        row = stage.sheet.rows["t5"]
        assert row.status_text() == "Running"
        assert row.fix_button is None and not row.is_failed()
    finally:
        stage.close()


def test_rows_fit_the_sheet_and_keep_their_height(stage):
    for row in stage.sheet.rows.values():
        assert row.height() == 56
        assert 500 < row.width() < 664
    fix = stage.sheet.rows["t5"].fix_button
    assert fix.geometry().right() < stage.sheet.rows["t5"].width() - 20


def test_clicking_a_row_opens_that_account(stage):
    seen = []
    stage.sheet.page_changed.connect(seen.append)
    click(stage.sheet.rows["t2"])
    assert stage.sheet.account_id() == "t2"
    assert seen[-1] == "t2"
    assert stage.header() == ("flossbud27", "Toontown Rewritten account")
    assert stage.back_visible()
    assert stage.sheet.login_form() is None


def test_the_back_button_returns_to_the_list(stage):
    stage.sheet.open_account("c1")
    assert stage.header() == ("flossbud", "Corporate Clash account")
    click(stage.host.panel.header.back_button)
    assert stage.sheet.account_id() is None
    assert stage.header()[0] == "Accounts"
    assert not stage.back_visible()
    assert "t1" in stage.sheet.rows


def test_a_failed_row_opens_on_fix_login(stage):
    click(stage.sheet.rows["t5"])
    form = stage.sheet.login_form()
    assert stage.sheet.account_id() == "t5"
    assert form is not None and form.mode() == m.FORM_FIX
    assert form.title_label.text() == "Fix login"
    assert form.username.text() == "flossbud3"


def test_the_fix_login_button_does_the_same(stage):
    click(stage.sheet.rows["t5"].fix_button)
    assert stage.sheet.account_id() == "t5"
    assert stage.sheet.login_form().mode() == m.FORM_FIX


def test_opening_an_unknown_account_is_refused(stage):
    assert stage.sheet.open_account("nope") is False
    assert stage.sheet.open_fix_login("nope") is False
    assert stage.sheet.account_id() is None


# ── Add account ────────────────────────────────────────────────────────────

def test_add_row_swaps_in_place_for_the_form(stage):
    sheet = stage.sheet
    assert sheet.add_rows["cc"].text() == "+  Add CC account"
    click(sheet.add_rows["cc"])
    form = sheet.add_form()
    assert isinstance(form, LoginForm) and form.mode() == m.FORM_ADD_ACCOUNT
    assert form.title_label.text() == "Add a Corporate Clash account"
    assert form.submit_button.text() == "Add account"
    assert sheet.cards["cc"].rows()[-1] is form
    assert "cc" not in sheet.add_rows and "ttr" in sheet.add_rows
    assert form.keep_toggle.isChecked() and form.keep_label.text() == m.KEEP_IN_KEYRING


def test_cancel_and_escape_put_the_add_row_back(stage):
    sheet = stage.sheet
    sheet.open_add_form("ttr")
    click(sheet.add_form().cancel_button)
    assert sheet.add_form() is None and "ttr" in sheet.add_rows
    sheet.open_add_form("ttr")
    QTest.keyClick(sheet.add_form().username, Qt.Key_Escape)
    assert sheet.add_form() is None
    assert stage.backend.calls == []


def test_username_is_required(stage):
    sheet = stage.sheet
    sheet.open_add_form("ttr")
    form = sheet.add_form()
    form.password.setText("secret")
    click(form.submit_button)
    assert form.error_text() == "Username is required"
    assert stage.backend.calls == [] and sheet.add_form() is form
    form.username.setText("x")
    form.username.textEdited.emit("x")
    assert form.error_text() == ""


def test_adding_an_account(stage):
    sheet = stage.sheet
    sheet.open_add_form("ttr")
    form = sheet.add_form()
    form.username.setText("  newbie  ")
    form.password.setText("pw with space ")
    QTest.keyClick(form.password, Qt.Key_Return)
    assert stage.backend.calls == [("add_account", "ttr", "newbie", "pw with space ", True)]
    assert sheet.add_form() is None
    assert sheet.cards["ttr"].meta_label.text() == "6 of 16 accounts"
    new_row = [r for r in sheet.rows.values() if r.title_text() == "newbie"]
    assert len(new_row) == 1 and new_row[0].status_text() == "Login saved"
    assert stage.header()[1].startswith("9 accounts")


def test_adding_without_keeping_the_login(stage):
    sheet = stage.sheet
    sheet.open_add_form("cc")
    form = sheet.add_form()
    form.username.setText("typed")
    form.password.setText("pw")
    form.keep_toggle.setChecked(False)
    click(form.submit_button)
    assert stage.backend.calls[-1] == ("add_account", "cc", "typed", "pw", False)
    row = [r for r in sheet.rows.values() if r.title_text() == "typed"][0]
    assert row.status_text() == "Asks at launch"


def test_without_a_keyring_the_form_says_so(qapp):
    backend = FakeAccountsBackend.demo(now=NOW)
    backend.set_keyring_available(False)
    stage = Stage(qapp, backend=backend)
    try:
        assert "cannot be saved" in stage.header()[1]
        stage.sheet.open_add_form("ttr")
        form = stage.sheet.add_form()
        assert not form.keep_toggle.isEnabled() and not form.keep_toggle.isChecked()
        assert form.keep_label.text() == m.KEYRING_UNAVAILABLE
        assert form.keep() is False
    finally:
        stage.close()


def test_the_add_row_is_disabled_at_sixteen_accounts(qapp):
    backend = FakeAccountsBackend.demo(now=NOW)
    for i in range(11):
        backend.add_account("ttr", f"u{i}", "pw", True)
    stage = Stage(qapp, backend=backend)
    try:
        assert stage.sheet.cards["ttr"].meta_label.text() == "16 of 16 accounts"
        assert not stage.sheet.add_rows["ttr"].isEnabled()
        assert stage.sheet.add_rows["cc"].isEnabled()
        assert stage.sheet.open_add_form("ttr") is False
        assert stage.sheet.add_form() is None
    finally:
        stage.close()


def test_what_is_typed_survives_a_change_underneath(stage):
    """An account starting to run, or a toon being discovered, must not wipe
    the form the user is in."""
    sheet = stage.sheet
    sheet.open_add_form("cc")
    form = sheet.add_form()
    form.username.setText("half-typed")
    form.password.setText("pw")
    stage.backend.update("t1", running=True)
    assert sheet.add_form() is form
    assert (form.username.text(), form.password.text()) == ("half-typed", "pw")
    assert sheet.cards["cc"].rows()[-1] is form
    assert sheet.rows["t1"].status_text() == "Running"


# ── One account: login ─────────────────────────────────────────────────────

def test_login_row_for_a_saved_login(stage):
    stage.sheet.open_account("t1")
    row = stage.sheet.login_row
    assert isinstance(row, LoginRow)
    assert row.status_line() == "Password saved in your system keyring"
    assert row.edit_button.text() == "Edit login"
    assert row.reset_button.text() == "Reset"


def test_login_row_for_a_rejected_login_shows_the_servers_reason(stage):
    stage.sheet.open_account("t5")
    row = stage.sheet.login_row
    assert row.status_line() == "The last sign-in was rejected. Check the password."
    assert row.edit_button.text() == "Fix login"
    assert stage.sheet.reason_label.text() == "Incorrect username or password."


def test_login_row_without_a_saved_login(stage):
    stage.backend.forget_login("t1")
    stage.sheet.open_account("t1")
    row = stage.sheet.login_row
    assert row.status_line() == "No saved login. You will be asked when you launch."
    assert row.edit_button.text() == "Add login"
    assert row.reset_button is None


def test_edit_login_replaces_the_row_with_the_form(stage):
    sheet = stage.sheet
    sheet.open_account("t1")
    click(sheet.login_row.edit_button)
    form = sheet.login_form()
    assert form.mode() == m.FORM_EDIT and form.title_label.text() == "Edit login"
    assert form.username.text() == "flossbud"
    assert form.submit_button.text() == "Save login"
    assert sheet.login_row is None
    assert sheet.login_card.rows() == [form]
    click(form.cancel_button)
    assert sheet.login_form() is None and sheet.login_row is not None


def test_saving_a_login(stage):
    sheet = stage.sheet
    sheet.open_fix_login("t5")
    form = sheet.login_form()
    form.password.setText("the right one")
    click(form.submit_button)
    assert stage.backend.calls == [
        ("save_login", "t5", "flossbud3", "the right one", True)]
    assert sheet.login_form() is None
    assert sheet.login_row.status_line() == "Password saved in your system keyring"
    assert sheet.account_id() == "t5"


def test_reset_asks_first_and_keep_it_changes_nothing(stage):
    sheet = stage.sheet
    sheet.open_account("t1")
    click(sheet.login_row.reset_button)
    confirm = sheet.confirm_row()
    assert isinstance(confirm, ConfirmRow)
    assert confirm.question_label.text() == "Forget the saved login for flossbud?"
    assert confirm.detail_label.text() == m.FORGET_DETAIL
    assert (confirm.keep_button.text(), confirm.confirm_button.text()) == (
        "Keep it", "Forget login")
    assert sheet.login_card.rows()[-1] is confirm
    click(confirm.keep_button)
    assert sheet.confirm_row() is None and stage.backend.calls == []


def test_forgetting_a_login_moves_the_account_to_none(stage):
    sheet = stage.sheet
    sheet.open_account("t1")
    click(sheet.login_row.reset_button)
    click(sheet.confirm_row().confirm_button)
    assert stage.backend.calls == [("forget_login", "t1")]
    assert sheet.confirm_row() is None
    assert sheet.login_row.edit_button.text() == "Add login"


# ── One account: toons ─────────────────────────────────────────────────────

def test_always_six_slots(stage):
    sheet = stage.sheet
    for account_id, filled in (("t2", 6), ("t1", 3), ("t5", 1), ("t4", 0)):
        sheet.open_account(account_id)
        assert len(sheet.slots) == 6
        assert [not s.is_empty() for s in sheet.slots] == [True] * filled + [False] * (6 - filled)
        assert sheet.toons_card.meta_label.text() == f"{filled} of 6"
        assert all(isinstance(s, ToonSlot) and s.height() == 150 for s in sheet.slots)


def test_slots_say_who_and_when(stage):
    stage.sheet.open_account("t2")
    first, second = stage.sheet.slots[0], stage.sheet.slots[1]
    assert (first.name_text(), first.line_text()) == ("Hector Pepperoni", "Duck · 96 laff")
    assert first.is_primary() and first.played_text() == "Primary · played yesterday"
    assert (second.name_text(), second.played_text()) == (
        "Loopy Sparklesnout", "played 4d ago")
    assert not second.is_primary()
    assert stage.sheet.toons_note.text() == m.TOONS_NOTE


def test_no_toons_yet(stage):
    stage.sheet.open_account("t4")
    assert stage.sheet.toons_note.text() == m.NO_TOONS_NOTE
    empty = stage.sheet.slots[0]
    assert (empty.name_text(), empty.line_text()) == (
        "Empty slot", "Shows up after you play this toon")
    assert empty.star is None and empty.pencil is None


def test_the_star_makes_a_toon_the_primary(stage):
    sheet = stage.sheet
    sheet.open_account("t2")
    click(sheet.slots[2].star)
    assert stage.backend.calls == [("set_primary", "t2", "Zippy McMuffin")]
    assert [s.is_primary() for s in sheet.slots] == [
        False, False, True, False, False, False]          # exactly one
    assert sheet.slots[2].star.is_primary()


def test_the_current_primarys_star_does_nothing(stage):
    sheet = stage.sheet
    sheet.open_account("t2")
    click(sheet.slots[0].star)
    assert stage.backend.calls == []
    assert sheet.slots[0].is_primary()


def test_the_pencil_opens_that_toons_look(stage):
    sheet = stage.sheet
    sheet.open_account("t2")
    click(sheet.slots[4].pencil)
    assert stage.backend.calls == [("open_appearance", "t2", "Quackers Von Zoom")]


def test_corporate_clash_accounts_get_six_slots_too(stage):
    stage.sheet.open_account("c2")
    assert len(stage.sheet.slots) == 6
    assert stage.sheet.slots[0].line_text() == "Cat"       # no laff from Clash
    assert stage.header() == ("clashmain", "Corporate Clash account")


# ── One account: label and removal ─────────────────────────────────────────

def test_the_label_is_saved_when_editing_ends(stage):
    sheet = stage.sheet
    sheet.open_account("t1")
    assert sheet.label_edit.placeholderText() == "e.g. Gag grind alt"
    assert sheet.label_edit.width() == 210
    sheet.label_edit.setText("  Main  ")
    sheet.label_edit.editingFinished.emit()
    assert stage.backend.calls == [("set_label", "t1", "Main")]
    assert stage.header()[0] == "Main"
    sheet.label_edit.editingFinished.emit()               # unchanged: no write
    assert len(stage.backend.calls) == 1


def test_remove_asks_first(stage):
    sheet = stage.sheet
    sheet.open_account("t3")
    click(sheet.remove_button)
    confirm = sheet.confirm_row()
    assert confirm.question_label.text() == "Remove hirofloss from the launcher?"
    assert sheet.account_card.layout() is not None
    click(confirm.keep_button)
    assert sheet.confirm_row() is None and stage.backend.account("t3") is not None


def test_removing_an_account_returns_to_the_list(stage):
    sheet = stage.sheet
    sheet.open_account("t3")
    click(sheet.remove_button)
    click(sheet.confirm_row().confirm_button)
    assert stage.backend.calls == [("remove_account", "t3")]
    assert sheet.account_id() is None
    assert "t3" not in sheet.rows
    assert stage.header() == (
        "Accounts", "7 accounts · logins are kept in your system keyring")
    assert not stage.back_visible()


def test_an_account_removed_underneath_returns_to_the_list(stage):
    stage.sheet.open_account("t3")
    stage.backend.remove_account("t3")
    assert stage.sheet.account_id() is None
    assert stage.header()[0] == "Accounts"


def test_a_change_underneath_keeps_the_login_form_and_updates_the_rest(stage):
    sheet = stage.sheet
    sheet.open_account("t1")
    click(sheet.login_row.edit_button)
    form = sheet.login_form()
    form.password.setText("typing")
    stage.backend.set_primary("t1", "Sir Hopper")
    assert sheet.login_form() is form and form.password.text() == "typing"
    assert [s.is_primary() for s in sheet.slots[:3]] == [False, True, False]


# ── Rendered ───────────────────────────────────────────────────────────────

def _has_colour(image, rect, target, tolerance=40):
    target = QColor(target)
    for x in range(rect.left(), rect.right(), 2):
        for y in range(rect.top(), rect.bottom(), 2):
            c = image.pixelColor(x, y)
            if (abs(c.red() - target.red()) + abs(c.green() - target.green())
                    + abs(c.blue() - target.blue())) <= tolerance:
                return True
    return False


def _rect_in_window(stage, widget):
    top_left = widget.mapTo(stage.window, widget.rect().topLeft())
    return widget.rect().translated(top_left)


def test_rendered_in_the_window_rows_carry_their_states(stage):
    image = stage.window.grab().toImage()
    running = _rect_in_window(stage, stage.sheet.rows["c2"])
    failed = _rect_in_window(stage, stage.sheet.rows["t5"])
    saved = _rect_in_window(stage, stage.sheet.rows["t1"])
    assert _has_colour(image, running, "#4fc95c")          # "Running" in green
    assert not _has_colour(image, saved.adjusted(0, 0, -200, 0), "#4fc95c")
    assert _has_colour(image, failed, "#ff7575")           # "Login failed"
    assert not _has_colour(image, saved, "#ff7575")
    # A row is the inset fill, not the app background showing through.
    inside = saved.adjusted(200, 20, -260, -20)
    assert not _has_colour(image, inside, "#1a1a1a", tolerance=6)


def test_light_theme_builds_and_reads(qapp):
    stage = Stage(qapp, is_dark=False)
    try:
        image = stage.window.grab().toImage()
        saved = _rect_in_window(stage, stage.sheet.rows["t1"])
        assert image.pixelColor(saved.center()).lightness() > 180
        stage.sheet.apply_theme(True)
        stage.settle(0.05)
        image = stage.window.grab().toImage()
        saved = _rect_in_window(stage, stage.sheet.rows["t1"])
        assert image.pixelColor(saved.center()).lightness() < 90
        assert stage.sheet.rows["t1"].status_text() == "Login saved"
    finally:
        stage.close()
