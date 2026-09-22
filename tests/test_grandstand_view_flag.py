"""The flag routes the launcher's view, and says so in the log."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from unittest.mock import MagicMock

from utils.widgets.grandstand.draft import MODE_ADD, MODE_EDIT, AccountDraft
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import (
    HERO_H, MILESTONE, PAGE_ROSTER, PAGE_SHEET, SELECTOR_H, SHEET_STAMP_PREFIX,
    STAMP_PREFIX, GrandstandView, grandstand_enabled,
)


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    assert grandstand_enabled() is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("", False)])
def test_flag_reads_the_env_var(monkeypatch, value, expected):
    monkeypatch.setenv("TTMT_GRANDSTAND", value)
    assert grandstand_enabled() is expected


def test_init_emits_the_startup_stamp(qapp):
    """CLAUDE.local.md running-code proof: never let the operator validate
    without evidence of which path is live. A human greps this exact line
    during live validation, so it is pinned verbatim, not by prefix."""
    lines = []
    GrandstandView(LaunchParty(None), log=lines.append)
    assert lines, "no stamp emitted"
    assert lines[0] == (
        f"{STAMP_PREFIX} — TTMT_GRANDSTAND=1 (milestone {MILESTONE})")
    assert lines[0] == "[Grandstand] view active — TTMT_GRANDSTAND=1 (milestone 1)"


def test_stack_fits_the_content_band(qapp):
    """main.py: 860 - HEADER_H(112) - NAV_BAND_H(60) = 688, no scrolling."""
    v = GrandstandView(LaunchParty(None))
    v.resize(880, 688)
    v.show()
    qapp.processEvents()
    assert v.selector.height() == SELECTOR_H
    assert v.hero.height() == HERO_H
    assert v.shelf.height() > 0
    total = (v.selector.height() + v.hero.height() + v.shelf.height())
    assert total <= 688


def test_set_accounts_is_callable_before_any_wiring(qapp):
    v = GrandstandView(LaunchParty(None))
    v.set_accounts("ttr", [])
    v.set_account_state("ttr", "nobody", "idle")   # unknown id must not raise


def test_theme_is_forwarded_to_the_crew_lineup(qapp):
    v = GrandstandView(LaunchParty(None))

    v.apply_theme(False)

    assert v.hero.crew_area._is_dark is False


def test_declares_every_signal_the_spec_names(qapp):
    v = GrandstandView(LaunchParty(None))
    for name in ("game_changed", "party_changed", "star_changed",
                 "launch_requested", "party_launch_requested", "edit_requested",
                 "cancel_requested", "quit_requested", "enter_2fa_requested",
                 "retry_requested", "add_account_requested", "manage_requested",
                 "official_launcher_requested",
                 "account_save_requested", "account_remove_requested",
                 "toon_chosen"):
        assert hasattr(v, name), f"missing signal {name}"


def test_layout_mode_does_not_resurrect_the_old_launcher(qapp, monkeypatch):
    """main.py calls this on resize; on the flagged path it must do nothing."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        assert getattr(tab, "_sections_container", None) is None
        for mode in ("full", "compact", "full"):
            tab.set_layout_mode(mode)
            assert getattr(tab, "_sections_container", None) is None
    finally:
        tab.shutdown()


def test_legacy_sections_are_hidden_on_the_flagged_path(qapp, monkeypatch):
    """Live-validated defect: both LaunchSections were parented to the scroll
    widget unconditionally and, being in no layout, painted at (0,0) over the
    Grandstand stack. The container test could not see this — the sections are
    visible independently of the container."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        tab.show()
        qapp.processEvents()
        assert tab.grandstand.isVisible() is True        # the baseline is real
        assert tab.ttr_section.isVisible() is False
        assert tab.cc_section.isVisible() is False
        for mode in ("full", "compact", "full"):
            tab.set_layout_mode(mode)
            tab.refresh_theme()
            qapp.processEvents()
            assert tab.ttr_section.isVisible() is False
            assert tab.cc_section.isVisible() is False
    finally:
        tab.shutdown()
        tab.close()


def test_legacy_sections_still_show_when_the_flag_is_off(qapp, monkeypatch):
    """The other direction: with the flag unset the old launcher is untouched."""
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        tab.show()
        qapp.processEvents()
        assert tab.ttr_section.isVisible() is True
        assert tab.cc_section.isVisible() is True
    finally:
        tab.shutdown()
        tab.close()


def test_populated_demo_fixtures_feed_the_grandstand_shelf(
        qapp, monkeypatch):
    """With both flags set the shelf shows the fixture accounts, and each
    card carries its fixture state — the way every card state is put on
    screen for milestone validation."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setenv("TTMT_DEMO_LAUNCH_TAB", "populated")
    from tabs.launch_tab import LaunchTab
    from utils.launch_tab_demo_mode import get_demo_fixtures

    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        fixtures = get_demo_fixtures()
        assert fixtures is not None
        for game in ("ttr", "cc"):
            if tab.grandstand.active_game() != game:
                tab.grandstand.selector.game_clicked.emit(game)
            cards = tab.grandstand.shelf.cards()
            assert [(card.entry().label, card.state()) for card in cards] == [
                (fixture["label"], fixture["state"])
                for fixture in fixtures[game]
            ]
        # The failure detail rides along with the state, not just its name.
        failed = next(f for f in fixtures["ttr"] if f["state"] == "failed")
        tab.grandstand.selector.game_clicked.emit("ttr")
        card = next(c for c in tab.grandstand.shelf.cards()
                    if c.entry().label == failed["label"])
        assert card.raw_error() == failed["raw"]
    finally:
        tab.shutdown()
        tab.close()


def test_demo_fixtures_survive_a_slot_reconcile(qapp, monkeypatch):
    """Demo mode exists to be clicked around. Account dialogs reconcile the
    slots against the credential store, which drops the fixture slots; the
    next render must rebuild them from the fixtures, not raise."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setenv("TTMT_DEMO_LAUNCH_TAB", "populated")
    from tabs.launch_tab import LaunchTab
    from utils.launch_tab_demo_mode import get_demo_fixtures

    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        tab._reconcile_slots()
        assert tab._slots["ttr"] == {}
        tab._render_current_view("ttr")
        assert [(c.entry().label, c.state())
                for c in tab.grandstand.shelf.cards()] == [
            (f["label"], f["state"]) for f in get_demo_fixtures()["ttr"]]
    finally:
        tab.shutdown()
        tab.close()


def test_starring_restyles_the_shelf_without_rebuilding_it(qapp, monkeypatch):
    """A star click is a refresh, not a render: the party persists the star
    itself, so rebuilding every card would only discard hover and focus."""
    from types import SimpleNamespace
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    from tabs.launch_tab import LaunchTab

    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    accounts = [
        SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                        password="pw", launcher_token="")
        for aid in ("a", "b")
    ]
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.return_value = accounts
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        before = tab.grandstand.shelf.card_for("a")
        before.clicked.emit("a")
        before.star_clicked.emit("a")
        after = tab.grandstand.shelf.card_for("a")
        assert after is before
        assert after.is_starred() is True
        assert tab._party.star("ttr") == "a"
    finally:
        tab.shutdown()
        tab.close()


def test_layout_mode_keeps_the_old_launcher_when_flag_is_off(qapp, monkeypatch):
    """The legacy launcher retains compact/full switching until cut-over."""
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        original = tab._sections_container
        assert original is not None
        tab.set_layout_mode("full")
        assert tab._sections_container is not None
        assert tab._sections_container is not original
        assert tab._layout_mode == "full"
    finally:
        tab.shutdown()


# ── focus mode: the account sheet (sub-project C) ───────────────────────────

def _entry(aid, state="idle"):
    return RosterEntry(account_id=aid, game="ttr", label=f"L{aid}",
                       username=f"u{aid}", toon_name="Flossbud", species="cat",
                       dna="7400", accent="#4a8fe7", footer="Primary",
                       portrait_mode="render", state=state, message="",
                       raw_error="")


def _draft(aid="a", mode=MODE_EDIT, **kw):
    base = dict(id=aid if mode == MODE_EDIT else "", game="ttr", mode=mode,
                label=f"L{aid}", username=f"u{aid}", password="pw",
                keyring_has_password=True)
    base.update(kw)
    return AccountDraft(**base)


@pytest.fixture
def roster(qapp):
    lines = []
    v = GrandstandView(LaunchParty(None), log=lines.append)
    v.set_accounts("ttr", [_entry("a"), _entry("b")])
    v.lines = lines
    yield v
    v.close()
    v.deleteLater()
    qapp.processEvents()


def test_open_account_sheet_enters_focus_mode_and_stamps(roster):
    assert roster.in_focus_mode() is False
    roster.open_account_sheet("ttr", _draft(), [], None)
    assert roster.in_focus_mode() is True
    assert roster.pages.currentIndex() == PAGE_SHEET
    assert roster.account_sheet.is_open() is True
    assert roster.sheet.header.title_text() == "Account · La"
    assert roster.sheet.header.subtitle_text() == (
        "Toontown Rewritten · changes apply to this account only")
    assert roster.sheet.note_text() == "No toons discovered yet"
    assert roster.lines[-1] == f"{SHEET_STAMP_PREFIX} account a"
    assert roster.lines[-1] == "[Grandstand] sheet: account a"


def test_the_sheet_takes_the_roster_entry_as_its_preview_base(roster):
    roster.set_account_state("ttr", "a", "running")
    roster.open_account_sheet("ttr", _draft(), [], None)
    assert roster.account_sheet.preview.state() == "running"


def test_launch_state_reaches_the_open_sheets_preview(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.set_account_state("ttr", "a", "need_2fa")
    assert roster.account_sheet.preview.state() == "need_2fa"
    roster.set_account_state("ttr", "b", "failed", "nope")   # someone else's
    assert roster.account_sheet.preview.state() == "need_2fa"


def test_close_sheet_returns_to_the_roster_and_drops_the_draft(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.account_sheet.label_input.setText("edited")
    roster.close_sheet()
    assert roster.in_focus_mode() is False
    assert roster.pages.currentIndex() == PAGE_ROSTER
    assert roster.account_sheet.is_open() is False
    assert roster.account_sheet.draft() is None


def test_back_and_cancel_close_without_emitting(roster):
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append(d))
    for button in (roster.sheet.back_button, roster.sheet.cancel_button):
        roster.open_account_sheet("ttr", _draft(), [], None)
        roster.account_sheet.label_input.setText("edited")
        button.click()
        assert roster.in_focus_mode() is False
    assert seen == []


def test_save_with_a_clean_draft_emits_the_intent_and_stays_open(roster):
    """The view never writes and never closes on its own: LaunchTab performs
    the write and calls close_sheet() afterwards (spec §3)."""
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append((g, d)))
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.account_sheet.label_input.setText("Main")
    roster.sheet.save_button.click()
    assert len(seen) == 1
    game, draft = seen[0]
    assert game == "ttr"
    assert (draft.id, draft.label, draft.username, draft.password) == (
        "a", "Main", "ua", "pw")
    assert roster.in_focus_mode() is True


def test_the_saved_draft_is_a_snapshot_not_the_live_one(roster):
    """The sheet stays open across the emit and its fields keep writing into
    the live draft, so the object handed to the owner must be a copy — or a
    consumer that holds it (a confirm dialog, a queued write) would read
    edits made after the Save it was told about."""
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append(d))
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.account_sheet.label_input.setText("Main")
    roster.sheet.save_button.click()
    recorded = seen[0]
    assert recorded is not roster.account_sheet.draft()
    assert recorded.label == "Main"
    roster.account_sheet.label_input.setText("edited after the save")
    assert roster.account_sheet.draft().label == "edited after the save"
    assert recorded.label == "Main"


def test_save_with_errors_does_not_emit(roster):
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append(d))
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.account_sheet.username_input.setText("")
    roster.sheet.save_button.click()
    assert seen == []
    assert roster.in_focus_mode() is True


def test_the_cross_link_routes_to_the_appearance_editor(roster):
    """Until sub-project B the cross-link does what the pencil does."""
    seen = []
    roster.edit_requested.connect(lambda g, a, s: seen.append((g, a, s)))
    roster.open_account_sheet("ttr", _draft(), [], None)
    assert roster.sheet.header.cross_link_text() == "✏ Customize appearance"
    roster.sheet.header.cross_link.click()
    assert seen == [("ttr", "a", "appearance")]


def test_a_game_click_in_focus_mode_closes_the_sheet_first(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.selector.game_clicked.emit("cc")
    assert roster.in_focus_mode() is False
    assert roster.active_game() == "cc"


def test_the_sheet_page_never_outgrows_the_content_band(roster, qapp):
    """QStackedWidget's minimum is the max over ALL pages, current or not."""
    roster.resize(880, 688)
    roster.show()
    qapp.processEvents()
    assert roster.minimumSizeHint().height() <= 688
    roster.open_account_sheet("ttr", _draft(), [], None)
    qapp.processEvents()
    assert roster.minimumSizeHint().height() <= 688
    assert roster.sheet.isVisible() is True
    assert roster.roster_page.isVisible() is False


def test_save_with_errors_renders_them_inline(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.account_sheet.username_input.setText("")
    roster.sheet.save_button.click()
    assert roster.account_sheet.username_error.text() == "Username is required"
    assert roster.account_sheet.errors() == {"username": "Username is required"}
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append(d))
    roster.account_sheet.username_input.setText("ua")
    roster.sheet.save_button.click()
    assert len(seen) == 1
    assert roster.account_sheet.errors() == {}


def test_add_mode_has_no_cross_link_and_stamps_add(roster):
    roster.open_account_sheet(
        "ttr", _draft(mode=MODE_ADD, label="", username="", password=""), [], None)
    assert roster.in_focus_mode() is True
    assert roster.sheet.header.title_text() == "Add account"
    assert roster.sheet.header.cross_link_text() == ""
    assert roster.sheet.note_text() == "No toons discovered yet"
    assert roster.lines[-1] == "[Grandstand] sheet: account add"
    seen = []
    roster.account_save_requested.connect(lambda g, d: seen.append(d))
    roster.account_sheet.username_input.setText("newbie")
    roster.account_sheet.password_input.setText("secret")
    roster.sheet.save_button.click()
    assert len(seen) == 1
    assert (seen[0].mode, seen[0].id, seen[0].username, seen[0].password) == (
        MODE_ADD, "", "newbie", "secret")


# ── remove + pruning (spec §3 "Remove", §4 "Account removed underneath") ────

def test_the_danger_button_emits_the_remove_intent(roster):
    seen = []
    roster.account_remove_requested.connect(lambda g, a: seen.append((g, a)))
    roster.open_account_sheet("ttr", _draft(), [], None)
    assert roster.account_sheet.remove_button.text().endswith(
        "Remove La from the launcher")
    roster.account_sheet.remove_button.click()
    assert seen == [("ttr", "a")]
    assert roster.in_focus_mode() is True        # the owner confirms and closes


def test_pruning_closes_the_sheet_for_a_vanished_account(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.set_accounts("ttr", [_entry("b")])     # "a" removed underneath
    assert roster.in_focus_mode() is False
    assert roster.account_sheet.is_open() is False


def test_a_refresh_keeps_a_surviving_sheet_and_updates_its_base(roster):
    roster.open_account_sheet("ttr", _draft(), [], None)
    roster.set_accounts("ttr", [_entry("a", state="failed"), _entry("b")])
    assert roster.in_focus_mode() is True
    assert roster.account_sheet.preview.state() == "failed"


def test_pruning_leaves_an_add_mode_sheet_alone(roster):
    roster.open_account_sheet(
        "ttr", _draft(mode=MODE_ADD, label="", username="", password=""), [], None)
    roster.set_accounts("ttr", [])
    assert roster.in_focus_mode() is True
