"""The Appearance editor in the view and in LaunchTab (design note §2).

The view holds no store and emits intents; LaunchTab performs every write.
One editing session can hold a draft for each surface; Save commits both.
"""
import copy
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from tabs.launch_tab import LaunchTab
from utils.recent_toons import RecentToonsStore, ToonRecord
from utils.widgets.grandstand.appearance_draft import AppearanceDraft
from utils.widgets.grandstand.draft import MODE_EDIT, AccountDraft
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import (
    PAGE_ROSTER, PAGE_SHEET, SHEET_STAMP_PREFIX, SURFACE_ACCOUNT,
    SURFACE_APPEARANCE, GrandstandView,
)

DNA = "74050102013b1b301bb31b12001212010400113800020000016000000000020800"


# ── the view ────────────────────────────────────────────────────────────────

def _entry(aid, toon="Flossbud"):
    return RosterEntry(account_id=aid, game="ttr", label=f"L{aid}",
                       username=f"u{aid}", toon_name=toon, species="dog",
                       dna=DNA if toon else "", accent="#4a8fe7",
                       footer="Primary" if toon else "No toon yet",
                       portrait_mode="render" if toon else "waiting",
                       state="idle", message="", raw_error="")


def _records():
    return [ToonRecord("Flossbud", "ttr", DNA, 137, 137, "dog", None),
            ToonRecord("Pepper", "ttr", "7401", 62, 137, "cat", None)]


def _look(aid="a", toon="Flossbud", entry=None):
    rec = next((r for r in _records() if r.toon_name == toon), None)
    return AppearanceDraft.for_record(
        account_id=aid, account_name=f"L{aid}", game="ttr", rec=rec,
        entry=entry or {})


def _account(aid="a", **kw):
    base = dict(id=aid, game="ttr", mode=MODE_EDIT, label=f"L{aid}",
                username=f"u{aid}", password="pw", keyring_has_password=True)
    base.update(kw)
    return AccountDraft(**base)


@pytest.fixture
def roster(qapp):
    """The view mounted in a host and shown: a surface that is constructed
    but never visible must not pass for one that works."""
    host = QWidget()
    host.resize(880, 688)
    lines = []
    view = GrandstandView(LaunchParty(None), log=lines.append, parent=host)
    view.setGeometry(0, 0, 880, 688)
    view.set_accounts("ttr", [_entry("a"), _entry("b"), _entry("n", toon=None)])
    view.lines = lines
    view.host = host
    host.show()
    qapp.processEvents()
    yield view
    host.close()
    host.deleteLater()
    qapp.processEvents()


def _signals(view):
    seen = []
    view._recorder = SimpleNamespace(
        look=lambda game, draft: seen.append(("look", game, draft)),
        account=lambda game, draft: seen.append(("account", game, draft)),
        edit=lambda game, aid, surface: seen.append(("edit", game, aid, surface)),
        toon=lambda game, aid, toon: seen.append(("toon", game, aid, toon)))
    view.appearance_save_requested.connect(view._recorder.look)
    view.account_save_requested.connect(view._recorder.account)
    view.edit_requested.connect(view._recorder.edit)
    view.subject_toon_chosen.connect(view._recorder.toon)
    return seen


def test_opening_the_editor_enters_focus_mode_and_stamps(roster, qapp, capsys):
    assert roster.in_focus_mode() is False
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    qapp.processEvents()
    assert roster.in_focus_mode() is True
    assert roster.pages.currentIndex() == PAGE_SHEET
    assert roster.surface() == SURFACE_APPEARANCE
    # Running-code proof, verbatim: live validation begins by confirming it.
    assert roster.lines[-1] == "[Grandstand] sheet: appearance ttr::Flossbud"
    assert roster.lines[-1].startswith(SHEET_STAMP_PREFIX)
    assert "[Grandstand] sheet: appearance ttr::Flossbud\n" in capsys.readouterr().out
    # The shell wears the appearance surface's copy.
    assert roster.sheet.header.title_text() == "Appearance · Flossbud"
    assert roster.sheet.header.subtitle_text() == (
        "Toontown Rewritten · this look follows Flossbud wherever the "
        "launcher shows it")
    assert roster.sheet.header.cross_link_text() == "⚙ Account settings"
    assert roster.sheet.note_text() == "Saves to toon_customizations.json · ttr::Flossbud"
    # And its body is the one on screen.
    assert roster.sheet.body() is roster.appearance_sheet
    assert roster.appearance_sheet.isVisible() is True
    assert roster.account_sheet.isVisible() is False
    assert roster.appearance_sheet.canvas.isVisible() is True


_READER_MODULES = ("appearance_sheet.py", "appearance_controls.py",
                   "appearance_draft.py", "look_paint.py", "view.py")
_WRITER_NAMES = ("toon_customizations_manager", "ToonCustomizationsManager",
                 "RecentToonsStore", "set_primary(", "self._customizations",
                 "settings_manager", "cred_manager")


def test_the_editor_and_the_view_hold_no_store():
    """Readers never write. None of the editor's modules, nor the view, may
    so much as name a store: every write is LaunchTab's."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "utils", "widgets", "grandstand")
    offenders = []
    for module in _READER_MODULES:
        with open(os.path.join(root, module), encoding="utf-8") as fh:
            text = fh.read()
        offenders += [f"{module}: {name}" for name in _WRITER_NAMES if name in text]
    assert offenders == []


def test_save_hands_the_owner_a_snapshot_and_does_not_close(roster, qapp):
    seen = _signals(roster)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[0], Qt.LeftButton)
    QTest.mouseClick(roster.sheet.save_button, Qt.LeftButton)
    assert [s[0] for s in seen] == ["look"]
    _kind, game, snapshot = seen[0]
    assert game == "ttr"
    assert snapshot is not roster.appearance_sheet.draft()
    assert snapshot.toon_name == "Flossbud" and snapshot.matching_look() == 0
    assert roster.in_focus_mode() is True                 # the owner closes it
    # A later edit must not reach what the owner was handed.
    roster.appearance_sheet.draft().accent = "#000000"
    assert snapshot.accent == "#4a8fe7"


def test_cancel_and_back_drop_the_draft_and_emit_nothing(roster, qapp):
    seen = _signals(roster)
    for button in ("cancel_button", "back_button"):
        roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
        QTest.mouseClick(roster.appearance_sheet.looks.swatches[3], Qt.LeftButton)
        QTest.mouseClick(getattr(roster.sheet, button), Qt.LeftButton)
        assert roster.in_focus_mode() is False
        assert roster.appearance_sheet.is_open() is False
    assert seen == []


def test_escape_closes_an_open_popover_first_and_then_the_sheet(roster, qapp):
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    editor = roster.appearance_sheet
    QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
    QTest.keyClick(editor.wells["accent"], Qt.Key_Escape)
    assert editor.swatch_popover.isVisible() is False
    assert roster.in_focus_mode() is True                 # Esc did not go Back
    QTest.keyClick(editor.wells["accent"], Qt.Key_Escape)
    assert roster.in_focus_mode() is False


def test_the_first_cross_link_asks_the_owner_for_the_other_surface(roster):
    seen = _signals(roster)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    roster.sheet.header.cross_link.click()
    assert seen == [("edit", "ttr", "a", "account")]


def test_switching_surfaces_keeps_both_drafts(roster, qapp):
    """Handoff §4.5: one editing session, two surfaces. What was typed on
    one is still there after a visit to the other."""
    seen = _signals(roster)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[5], Qt.LeftButton)
    # The owner answers the first cross-link by opening the account surface.
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    qapp.processEvents()
    assert roster.surface() == SURFACE_ACCOUNT
    assert roster.sheet.body() is roster.account_sheet
    assert roster.account_sheet.isVisible() is True
    assert roster.appearance_sheet.isVisible() is False
    assert roster.appearance_sheet.draft().matching_look() == 5      # kept
    assert roster.sheet.header.title_text() == "Account · La"
    assert roster.sheet.header.cross_link_text() == "✏ Customize appearance"
    roster.account_sheet.label_input.setText("Gag grind alt")
    del seen[:]

    # Back again: a surface already visited returns as it was left, with no
    # round trip to the owner (which would rebuild it from the store).
    roster.sheet.header.cross_link.click()
    qapp.processEvents()
    assert seen == []
    assert roster.surface() == SURFACE_APPEARANCE
    assert roster.appearance_sheet.isVisible() is True
    assert roster.appearance_sheet.looks.selected() == 5
    assert roster.sheet.header.title_text() == "Appearance · Flossbud"
    roster.sheet.header.cross_link.click()
    assert seen == []
    assert roster.account_sheet.draft().label == "Gag grind alt"
    assert roster.account_sheet.label_input.text() == "Gag grind alt"


def test_the_account_preview_wears_the_look_being_edited(roster, qapp):
    """Handoff §4.4: an accent change is judged where it will be seen."""
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[5], Qt.LeftButton)   # Ember
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    assert roster.account_sheet.preview_entry().accent == "#e74a4a"
    assert roster.entry_for("ttr", "a").accent == "#4a8fe7"          # nothing stored


def test_save_commits_both_halves_the_look_first(roster, qapp):
    seen = _signals(roster)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[5], Qt.LeftButton)
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.label_input.setText("Gag grind alt")
    del seen[:]
    QTest.mouseClick(roster.sheet.save_button, Qt.LeftButton)
    assert [s[0] for s in seen] == ["look", "account"]
    assert seen[0][2].matching_look() == 5
    assert seen[1][2].label == "Gag grind alt"


def test_both_halves_survive_an_owner_that_closes_on_the_first_intent(roster, qapp):
    """LaunchTab closes the sheet from the handler it runs first, which
    clears both drafts. The second intent must still carry its snapshot."""
    seen = _signals(roster)
    roster.appearance_save_requested.connect(roster.close_sheet)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[5], Qt.LeftButton)
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.label_input.setText("Gag grind alt")
    del seen[:]
    QTest.mouseClick(roster.sheet.save_button, Qt.LeftButton)
    assert [s[0] for s in seen] == ["look", "account"]
    assert seen[1][2].label == "Gag grind alt"
    assert roster.in_focus_mode() is False


def test_an_invalid_account_half_blocks_save_and_comes_forward(roster, qapp):
    seen = _signals(roster)
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.username_input.setText("")
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    qapp.processEvents()
    assert roster.surface() == SURFACE_APPEARANCE
    del seen[:]
    QTest.mouseClick(roster.sheet.save_button, Qt.LeftButton)
    qapp.processEvents()
    assert seen == []                                     # nothing half-saved
    assert roster.surface() == SURFACE_ACCOUNT            # where the message is
    assert roster.account_sheet.isVisible() is True
    assert roster.account_sheet.errors() == {"username": "Username is required"}
    assert roster.in_focus_mode() is True


def test_a_fresh_open_from_the_roster_starts_a_new_session(roster, qapp):
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.label_input.setText("typed")
    roster.close_sheet()
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    assert roster.account_sheet.is_open() is False
    roster.close_sheet()
    # And a different account never inherits the other's draft.
    roster.open_appearance_sheet("ttr", _look("a"), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[1], Qt.LeftButton)
    roster.open_account_sheet("ttr", _account("b"), _records(), "Flossbud")
    assert roster.appearance_sheet.is_open() is False


def test_the_subject_switcher_emits_the_pick_for_the_owner(roster, qapp):
    seen = _signals(roster)
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    editor = roster.appearance_sheet
    QTest.mouseClick(editor.pill, Qt.LeftButton)
    QTest.mouseClick(editor.switcher.row_for("Pepper"), Qt.LeftButton)
    assert seen == [("toon", "ttr", "a", "Pepper")]
    assert editor.draft().toon_name == "Flossbud"         # the owner re-opens it


def test_reopening_on_the_adopted_toon_rebuilds_the_hero(roster, qapp, monkeypatch):
    """Handoff §6.3: a new identity is rebuilt, not diffed into place."""
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    calls = []
    real = roster.hero.set_lineup
    monkeypatch.setattr(roster.hero, "set_lineup",
                        lambda entries: (calls.append(len(entries)), real(entries))[1])
    roster.open_appearance_sheet("ttr", _look(toon="Pepper"), _records(), "Pepper",
                                 identity_changed=True)
    assert calls and calls[0] == 0                        # emptied first
    assert roster.sheet.header.title_text() == "Appearance · Pepper"
    assert roster.lines[-1] == "[Grandstand] sheet: appearance ttr::Pepper"


def test_an_account_with_no_toon_opens_the_explanation_and_saves_nothing(roster, qapp):
    seen = _signals(roster)
    draft = AppearanceDraft.for_record(account_id="n", account_name="Ln",
                                       game="ttr", rec=None, entry={})
    roster.open_appearance_sheet("ttr", draft, [], None)
    assert roster.lines[-1] == "[Grandstand] sheet: appearance ttr::(no toon)"
    assert roster.sheet.header.title_text() == "Appearance · Ln"
    assert roster.sheet.note_text() == "Nothing to save until a toon is discovered"
    QTest.mouseClick(roster.sheet.save_button, Qt.LeftButton)
    assert seen == []                                     # a look is stored per toon
    assert roster.in_focus_mode() is False                # Save is Back


def test_an_account_removed_underneath_closes_the_editor(roster):
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    roster.set_accounts("ttr", [_entry("b")])
    assert roster.in_focus_mode() is False
    assert roster.appearance_sheet.is_open() is False


def test_a_theme_switch_reaches_the_surface_that_is_not_showing(roster, monkeypatch):
    seen = []
    monkeypatch.setattr(roster.appearance_sheet, "apply_theme", seen.append)
    assert roster.sheet.body() is roster.account_sheet
    roster.apply_theme(False)
    assert seen == [False]


def test_a_browser_pick_drops_an_untouched_look_and_keeps_an_edited_one(roster):
    """The session's look was for the toon the account no longer shows."""
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.choose_button.click()
    roster.close_toon_browser(primary_name="Pepper")
    assert roster.appearance_sheet.is_open() is False     # the link reopens Pepper's

    roster.close_sheet()
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    QTest.mouseClick(roster.appearance_sheet.looks.swatches[2], Qt.LeftButton)
    roster.open_account_sheet("ttr", _account(), _records(), "Flossbud")
    roster.account_sheet.choose_button.click()
    roster.close_toon_browser(primary_name="Pepper")
    assert roster.appearance_sheet.draft().toon_name == "Flossbud"   # edits kept


# ── the short band (a real laptop measured 646 px, not 688) ─────────────────

def _fits(view, width, height, qapp):
    view.host.resize(width, height)
    view.setGeometry(0, 0, width, height)
    qapp.processEvents()
    qapp.processEvents()


@pytest.mark.parametrize("size", [(880, 688), (828, 646)])
def test_the_editor_fits_the_band_without_scrolling(roster, qapp, size):
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    _fits(roster, *size, qapp)
    editor = roster.appearance_sheet
    assert editor.scroll.verticalScrollBar().maximum() == 0
    host_rect = roster.host.rect()
    for widget in (roster.sheet.save_button, roster.sheet.cancel_button,
                   editor.pose_strip, editor.canvas, editor.zoom_row,
                   editor.turn_row, editor.looks):
        assert widget.isVisible()
        top_left = widget.mapTo(roster.host, QPoint(0, 0))
        bottom_right = widget.mapTo(roster.host, QPoint(widget.width(), widget.height()))
        assert host_rect.contains(top_left) and host_rect.contains(
            bottom_right - QPoint(1, 1)), (size, widget)


def test_the_longest_pattern_chip_still_fits_the_narrowest_window(roster, qapp):
    """The window's minimum width is 820. A look carrying one of the store's
    other patterns adds a fifth chip; the row must give way (its hex readout
    elides) rather than push the column past the sheet's edge."""
    entry = {"portrait": {"pattern": {"name": "stripes_horiz", "color": "#e74ab0"}}}
    roster.open_appearance_sheet("ttr", _look(entry=entry), _records(), "Flossbud")
    _fits(roster, 820, 646, qapp)
    editor = roster.appearance_sheet
    assert [c.text() for c in editor.pattern_chips.chips()][-1] == "Stripes horiz"
    viewport = editor.scroll.viewport().width()
    assert editor.columns.minimumSizeHint().width() <= viewport
    assert editor.columns.width() <= viewport
    well = editor.wells["pat_color"]
    assert well.isVisible()
    right = well.mapTo(editor, QPoint(well.width(), 0)).x()
    assert right <= editor.width()


def test_a_band_too_short_scrolls_the_body_inside_the_sheet_never_the_window(
        roster, qapp):
    roster.open_appearance_sheet("ttr", _look(), _records(), "Flossbud")
    _fits(roster, 828, 520, qapp)
    editor = roster.appearance_sheet
    assert editor.scroll.verticalScrollBar().maximum() > 0
    assert roster.host.size().height() == 520             # the window did not grow
    # The editor asks for less than the roster does, so it can never be the
    # reason the window grows or the tab scrolls.
    assert roster.sheet.minimumSizeHint().height() < 520
    assert (roster.sheet.minimumSizeHint().height()
            < roster.roster_page.minimumSizeHint().height())
    # The footer stays put, and so does the subject row.
    for widget in (roster.sheet.save_button, editor.pill):
        bottom = widget.mapTo(roster.host, QPoint(0, widget.height())).y()
        assert 0 < bottom <= 520, widget


# ── LaunchTab: every write lives here ───────────────────────────────────────

class _Looks:
    """A ToonCustomizationsManager stand-in with the same copy semantics."""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.sets = []

    def get(self, game, name):
        return copy.deepcopy(self.entries.get((game, name), {}))

    def set(self, game, name, entry):
        self.sets.append((game, name, copy.deepcopy(entry)))
        if entry:
            self.entries[(game, name)] = copy.deepcopy(entry)
        else:
            self.entries.pop((game, name), None)


def _recent_toons_store():
    values = {}
    return RecentToonsStore(SimpleNamespace(
        get=lambda key, default=None: values.get(key, default),
        set=lambda key, value: values.__setitem__(key, value)))


def _make_tab(monkeypatch, account_ids=("a",), *, flagged=True, looks=None):
    if flagged:
        monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    else:
        monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    accounts = [SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                                password="pw", launcher_token="")
                for aid in account_ids]
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False,
                     macos_unlock_state="unlocked")
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account_metadata.side_effect = lambda index: accounts[index]
    cred.get_account.side_effect = lambda index: accounts[index]
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    tab._recent_toons = _recent_toons_store()
    tab._recent_toons.record("a", "Pepper", "ttr", "7401", species="cat", laff=62)
    tab._recent_toons.record("a", "Flossbud", "ttr", DNA, species="dog", laff=137)
    tab._customizations = looks if looks is not None else _Looks()
    if flagged:
        tab._render_grandstand("ttr")
    return tab, cred


def _close(tab):
    tab.shutdown()
    tab.close()


def _pencil(tab, aid="a"):
    tab.grandstand.shelf.card_for(aid).edit_clicked.emit(aid)
    return tab.grandstand.appearance_sheet


FULL = {
    "accent": "#e74a4a", "body": "#123456", "pose": "waving",
    "portrait": {
        "color": "#4a8fe7",
        "pattern": {"name": "hearts", "color": "#ffffff"},
        "silhouette": {"outline": {"color": "#000000", "width": "thin"}},
    },
}


def test_the_pencil_opens_the_editor_on_the_toon_the_account_shows(
        monkeypatch, qapp, capsys):
    tab, _cred = _make_tab(monkeypatch, looks=_Looks({("ttr", "Flossbud"): FULL}))
    legacy = []
    tab.appearance_requested.connect(legacy.append)
    try:
        editor = _pencil(tab)
        assert tab.grandstand.in_focus_mode() is True
        assert tab.grandstand.surface() == SURFACE_APPEARANCE
        assert editor.draft().toon_name == "Flossbud"
        assert editor.draft().account_name == "a"
        assert editor.draft().base == FULL                 # the stored look
        assert editor.draft().accent == "#e74a4a"
        assert editor.toon_count() == 2
        assert legacy == []                                # not the old overlay
        assert "[Grandstand] sheet: appearance ttr::Flossbud" in capsys.readouterr().out
    finally:
        _close(tab)


def test_save_writes_the_merged_look_and_both_readers_follow(monkeypatch, qapp):
    looks = _Looks({("ttr", "Flossbud"): FULL})
    tab, _cred = _make_tab(monkeypatch, looks=looks)
    saved = []
    tab.look_saved.connect(lambda game, name: saved.append((game, name)))
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.wells["accent"], Qt.LeftButton)
        pick = next(s for s in editor.swatch_popover.swatches() if s.hex == "#56c856")
        QTest.mouseClick(pick, Qt.LeftButton)
        tab.grandstand.sheet.save_button.click()

        expected = copy.deepcopy(FULL)
        expected["accent"] = "#56c856"
        assert looks.sets == [("ttr", "Flossbud", expected)]   # one write, keys kept
        assert tab.grandstand.in_focus_mode() is False
        # This tab's cards repainted from the store...
        assert tab.grandstand.entry_for("ttr", "a").accent == "#56c856"
        assert tab.grandstand.shelf.card_for("a").entry().accent == "#56c856"
        # ...and the window is told which toon, for its Multitoon slots.
        assert saved == [("ttr", "Flossbud")]
    finally:
        _close(tab)


def test_an_untouched_save_writes_nothing_and_still_closes(monkeypatch, qapp):
    looks = _Looks({("ttr", "Flossbud"): FULL})
    tab, _cred = _make_tab(monkeypatch, looks=looks)
    saved = []
    tab.look_saved.connect(lambda game, name: saved.append((game, name)))
    try:
        _pencil(tab)
        tab.grandstand.sheet.save_button.click()
        assert looks.sets == [] and saved == []
        assert looks.entries[("ttr", "Flossbud")] == FULL
        assert tab.grandstand.in_focus_mode() is False
    finally:
        _close(tab)


def test_save_merges_onto_a_look_saved_elsewhere_while_the_sheet_was_open(
        monkeypatch, qapp):
    looks = _Looks({("ttr", "Flossbud"): {"accent": "#e74a4a"}})
    tab, _cred = _make_tab(monkeypatch, looks=looks)
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.pattern_chips.chip("dots"), Qt.LeftButton)
        # The Multitoon tab's customizer saves a body colour meanwhile.
        looks.entries[("ttr", "Flossbud")] = {"accent": "#4ae7d9", "body": "#222222"}
        tab.grandstand.sheet.save_button.click()
        assert looks.entries[("ttr", "Flossbud")] == {
            "accent": "#4ae7d9", "body": "#222222",
            "portrait": {"pattern": {"name": "dots", "color": "#ffffff"}}}
    finally:
        _close(tab)


def test_cancel_writes_nothing(monkeypatch, qapp):
    looks = _Looks({("ttr", "Flossbud"): FULL})
    tab, _cred = _make_tab(monkeypatch, looks=looks)
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.looks.swatches[0], Qt.LeftButton)
        tab.grandstand.sheet.cancel_button.click()
        assert looks.sets == []
        assert tab.grandstand.in_focus_mode() is False
    finally:
        _close(tab)


def test_the_real_store_round_trips_what_the_editor_did_not_touch(
        monkeypatch, qapp, tmp_path):
    """End to end against ToonCustomizationsManager and its file: the keys
    the old customizer wrote and this editor has no control for are still on
    disk after a Save here."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "cfg"))
    from utils.toon_customizations_manager import ToonCustomizationsManager
    manager = ToonCustomizationsManager()
    manager.set("ttr", "Flossbud", FULL)
    path = manager._path
    assert str(tmp_path) in path                           # never the real config
    tab, _cred = _make_tab(monkeypatch, looks=manager)
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.looks.swatches[6], Qt.LeftButton)      # Midnight
        tab.grandstand.sheet.save_button.click()
        with open(path, encoding="utf-8") as fh:
            on_disk = json.load(fh)["ttr::Flossbud"]
        assert on_disk["body"] == "#123456"
        assert on_disk["pose"] == "waving"
        assert on_disk["portrait"]["silhouette"] == FULL["portrait"]["silhouette"]
        assert on_disk["accent"] == "#4a5fe7"
        assert on_disk["portrait"]["gradient"] == {"start": "#4a5fe7", "end": "#1a1d29"}
        assert "color" not in on_disk["portrait"]
        assert on_disk["portrait"]["pattern"] == {"name": "dots", "color": "#ffffff"}
        # A second manager, as after a restart, reads the same thing.
        assert ToonCustomizationsManager().get("ttr", "Flossbud") == on_disk
    finally:
        _close(tab)


def test_switching_toons_pins_the_pick_and_reopens_on_its_saved_look(
        monkeypatch, qapp):
    looks = _Looks({("ttr", "Pepper"): {"accent": "#b04ae7", "pose": "head"}})
    tab, _cred = _make_tab(monkeypatch, looks=looks)
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.looks.swatches[0], Qt.LeftButton)   # unsaved, dropped
        QTest.mouseClick(editor.pill, Qt.LeftButton)
        assert editor.switcher.is_warning() is True
        QTest.mouseClick(editor.switcher.row_for("Pepper"), Qt.LeftButton)

        assert tab._recent_toons.primary_name("a") == "Pepper"       # the write
        assert tab.grandstand.in_focus_mode() is True
        d = editor.draft()
        assert d.toon_name == "Pepper"
        assert (d.accent, d.pose) == ("#b04ae7", "head")             # Pepper's look
        assert d.is_dirty() is False
        assert tab.grandstand.sheet.header.title_text() == "Appearance · Pepper"
        assert tab.grandstand.shelf.card_for("a").entry().toon_name == "Pepper"
        assert looks.sets == []                                      # the look was discarded
    finally:
        _close(tab)


def test_the_cross_link_keeps_what_was_typed_and_save_writes_both(monkeypatch, qapp):
    looks = _Looks()
    tab, cred = _make_tab(monkeypatch, looks=looks)
    try:
        tab.grandstand.shelf.card_for("a").gear_clicked.emit("a")
        account = tab.grandstand.account_sheet
        account.label_input.setText("Gag grind alt")
        tab.grandstand.sheet.header.cross_link.click()               # -> appearance
        editor = tab.grandstand.appearance_sheet
        assert tab.grandstand.surface() == SURFACE_APPEARANCE
        assert editor.draft().toon_name == "Flossbud"
        assert account.draft().label == "Gag grind alt"
        QTest.mouseClick(editor.looks.swatches[4], Qt.LeftButton)    # Lagoon
        tab.grandstand.sheet.header.cross_link.click()               # -> account
        assert tab.grandstand.surface() == SURFACE_ACCOUNT
        assert account.label_input.text() == "Gag grind alt"
        tab.grandstand.sheet.save_button.click()

        assert looks.entries[("ttr", "Flossbud")]["accent"] == "#4ae7d9"
        cred.update_account.assert_called_once()
        assert cred.update_account.call_args.kwargs["label"] == "Gag grind alt"
        assert tab.grandstand.in_focus_mode() is False
    finally:
        _close(tab)


def test_a_toonless_account_opens_the_explanation_and_never_writes(monkeypatch, qapp):
    looks = _Looks()
    tab, _cred = _make_tab(monkeypatch, account_ids=("a", "z"), looks=looks)
    try:
        editor = _pencil(tab, "z")                         # a stray signal: its pencil is disabled
        assert tab.grandstand.in_focus_mode() is True
        assert editor.draft().has_toon is False
        assert editor.controls.isEnabled() is False
        tab.grandstand.sheet.save_button.click()
        assert looks.sets == []
        assert tab.grandstand.in_focus_mode() is False
    finally:
        _close(tab)


def test_without_a_customizations_store_save_closes_and_writes_nothing(
        monkeypatch, qapp):
    tab, _cred = _make_tab(monkeypatch)
    tab._customizations = None
    try:
        editor = _pencil(tab)
        QTest.mouseClick(editor.looks.swatches[0], Qt.LeftButton)
        tab.grandstand.sheet.save_button.click()
        assert tab.grandstand.in_focus_mode() is False
    finally:
        _close(tab)


def test_every_handler_is_inert_when_grandstand_is_not_mounted(monkeypatch, qapp):
    """The unflagged launcher must not change: no write, no error."""
    looks = _Looks({("ttr", "Flossbud"): FULL})
    tab, _cred = _make_tab(monkeypatch, flagged=False, looks=looks)
    saved = []
    tab.look_saved.connect(lambda game, name: saved.append((game, name)))
    try:
        assert tab._grandstand_mounted() is False
        draft = AppearanceDraft.for_record(
            account_id="a", account_name="a", game="ttr",
            rec=tab._recent_toons.get("a"), entry=FULL)
        draft.accent = "#000000"
        tab._on_appearance_save("ttr", draft)
        tab._on_subject_toon_chosen("ttr", "a", "Pepper")
        tab._open_appearance_sheet("ttr", "a")
        assert looks.sets == [] and saved == []
        assert tab._recent_toons.primary_name("a") is None
    finally:
        _close(tab)
