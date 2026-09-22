"""Account settings body: fields <-> draft, the real-card preview, the toon
row, copy and measurements (handoff §4.4)."""
import os
import os as _os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit

from tests._render_fixtures import complete_set, real_png
from utils.toon_renders import AWAITING_RENDER_TOOLTIP
from utils.recent_toons import ToonRecord
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.account_sheet import (
    ADD_TITLE, CAPTION, CHOOSE_TOON, COL_GAP, CROSS_LINK, DANGER_FIELD,
    EYE_GLYPH, EYE_SIZE, FROW_FIELD, FROW_H, FROW_NO_TOON, FROW_PORTRAIT,
    FROW_SUB_NONE, INPUT_H, LABEL_FIELD, LABEL_PLACEHOLDER, LINKBTN_H,
    PASSWORD_FIELD, PREVIEW_COL_W, TRASH_GLYPH, USERNAME_FIELD, AccountSheet,
    frow_sub_for, note_for, remove_label_for, subtitle_for, title_for,
)
from utils.widgets.grandstand.draft import (
    MODE_ADD, MODE_EDIT, PASSWORD_REQUIRED, USERNAME_REQUIRED, AccountDraft,
)
from utils.widgets.grandstand.model import CARD_POSE, RosterEntry
from utils.widgets.grandstand.roster_card import CARD_H, CARD_W, RosterCard


def _draft(mode=MODE_EDIT, **kw):
    base = dict(id="a" if mode == MODE_EDIT else "", game="ttr", mode=mode,
                label="Gag alt", username="flossbud", password="pw",
                keyring_has_password=True, keyring_readable=True)
    base.update(kw)
    return AccountDraft(**base)


def _rec(name="Flossbud", dna="7400", game="ttr", species="cat", laff=137):
    return ToonRecord(name, game, dna, laff, None, species, None)


def _entry(aid="a", state="idle", accent="#4a8fe7"):
    return RosterEntry(account_id=aid, game="ttr", label="Gag alt",
                       username="flossbud", toon_name="Flossbud", species="cat",
                       dna="7400", accent=accent, footer="Primary",
                       portrait_mode="render", state=state, message="",
                       raw_error="")


@pytest.fixture
def sheet(qapp, render_cache):
    s = AccountSheet()
    yield s
    s.close()
    s.deleteLater()
    qapp.processEvents()


def _open(sheet, draft=None, toons=None, primary="Flossbud", base=None):
    sheet.open(draft or _draft(), [_rec()] if toons is None else toons,
               primary, base)
    return sheet


# ── fields <-> draft ────────────────────────────────────────────────────────

def test_fields_are_seeded_from_the_draft(sheet):
    _open(sheet)
    assert sheet.label_input.text() == "Gag alt"
    assert sheet.username_input.text() == "flossbud"
    assert sheet.password_input.text() == "pw"
    assert sheet.label_input.placeholderText() == LABEL_PLACEHOLDER
    assert sheet.is_open() is True
    assert sheet.account_id() == "a"


def test_edits_flow_into_the_draft(sheet):
    _open(sheet)
    changes = []
    sheet.changed.connect(lambda: changes.append(1))
    sheet.label_input.setText("Main")
    sheet.username_input.setText("floss")
    sheet.password_input.setText("new")
    d = sheet.draft()
    assert (d.label, d.username, d.password) == ("Main", "floss", "new")
    assert d.id == "a" and d.mode == MODE_EDIT
    assert len(changes) == 3


def test_clear_drops_the_draft(sheet):
    _open(sheet)
    sheet.clear()
    assert sheet.is_open() is False
    assert sheet.draft() is None
    assert sheet.account_id() == ""
    assert sheet.label_input.text() == ""


# ── the preview ─────────────────────────────────────────────────────────────

def test_preview_is_the_real_card_mouse_transparent_and_unfocusable(sheet):
    assert isinstance(sheet.preview, RosterCard)
    assert (sheet.preview.width(), sheet.preview.height()) == (CARD_W, CARD_H)
    assert sheet.preview.testAttribute(Qt.WA_TransparentForMouseEvents) is True
    for chip in (sheet.preview, sheet.preview.ribbon, sheet.preview.star,
                 sheet.preview.pencil, sheet.preview.gear, sheet.preview.action):
        assert chip.focusPolicy() == Qt.NoFocus


def test_preview_shows_the_primary_toon_with_the_drafts_text(sheet):
    _open(sheet)
    e = sheet.preview_entry()
    assert e.display_name == "Flossbud"
    assert e.username == "flossbud"
    assert e.label == "Gag alt"
    assert e.footer == "Primary"
    assert sheet.preview.name_text() == "Flossbud"
    assert sheet.preview.user_text() == "flossbud"


def test_preview_reads_its_head_from_the_cache(sheet, render_cache):
    _facade, store, _pf = render_cache
    complete_set(store, "ttr", "Flossbud", "7400", "#ff0000")
    _open(sheet)
    assert sheet.preview.portrait_pixmap() is not None
    assert sheet.preview.requested_pose() == CARD_POSE


def test_base_entry_seeds_the_previews_state_and_accent(sheet):
    _open(sheet, base=_entry(state="running", accent="#123456"))
    assert sheet.preview.state() == "running"
    assert sheet.preview_entry().accent == "#123456"
    assert sheet.preview.footer_text() == "Running"


def test_caption_is_the_handoff_copy_uppercased(sheet):
    assert CAPTION == "Live preview · launcher card"
    assert sheet.caption.text() == "LIVE PREVIEW · LAUNCHER CARD"


# ── fields, copy, measurements ──────────────────────────────────────────────

def test_field_labels_are_the_handoff_copy(sheet):
    assert (LABEL_FIELD, USERNAME_FIELD, PASSWORD_FIELD, FROW_FIELD, DANGER_FIELD) == (
        "Label (optional)", "Username", "Password", "Toon this account shows",
        "Danger zone")
    texts = [label.text() for label in sheet.section_labels()]
    assert texts == ["LABEL (OPTIONAL)", "USERNAME", "PASSWORD",
                     "TOON THIS ACCOUNT SHOWS", "DANGER ZONE"]
    assert sheet.choose_button.text() == CHOOSE_TOON == "Choose toon"
    assert CROSS_LINK == "✏ Customize appearance"
    assert ADD_TITLE == "Add account"
    assert title_for(_draft(MODE_ADD)) == ADD_TITLE
    assert TRASH_GLYPH == "🗑"
    assert EYE_GLYPH == "👁"
    assert sheet.password_input.eye.text() == EYE_GLYPH


def test_password_is_masked_with_a_22px_eye_toggle(sheet):
    _open(sheet)
    assert sheet.password_input.echoMode() == QLineEdit.Password
    assert sheet.password_input.is_revealed() is False
    eye = sheet.password_input.eye
    assert (eye.width(), eye.height()) == (EYE_SIZE, EYE_SIZE) == (22, 22)
    eye.click()
    assert sheet.password_input.echoMode() == QLineEdit.Normal
    assert sheet.password_input.is_revealed() is True
    eye.click()
    assert sheet.password_input.echoMode() == QLineEdit.Password


def test_reopening_masks_the_password_again(sheet):
    _open(sheet)
    sheet.password_input.eye.click()
    _open(sheet)
    assert sheet.password_input.is_revealed() is False


def test_handoff_focus_mode_measurements(sheet):
    assert (PREVIEW_COL_W, COL_GAP, INPUT_H, FROW_H, FROW_PORTRAIT, LINKBTN_H) == (
        184, 26, 38, 64, 44, 26)
    assert sheet.preview_column.width() == PREVIEW_COL_W
    for edit in (sheet.label_input, sheet.username_input, sheet.password_input):
        assert edit.height() == INPUT_H
    assert sheet.frow.height() == FROW_H
    assert sheet.choose_button.height() == LINKBTN_H


# ── the toon row ────────────────────────────────────────────────────────────

def test_frow_shows_the_primary_name_and_the_count(sheet):
    _open(sheet, toons=[_rec("Pepper", "7401"), _rec("Flossbud", "7400")],
          primary="Flossbud")
    assert sheet.frow_name_text() == "Flossbud"
    assert sheet.frow_sub_text() == "2 discovered"
    assert sheet.toon_count() == 2
    assert sheet.primary_record().toon_name == "Flossbud"


def test_frow_without_toons(sheet):
    _open(sheet, toons=[], primary=None)
    assert sheet.frow_name_text() == FROW_NO_TOON == "No toon yet"
    assert sheet.frow_sub_text() == FROW_SUB_NONE == "play once to discover"
    assert sheet.toon_count() == 0
    assert sheet.primary_record() is None
    assert sheet.preview_entry().toon_name is None


def test_choose_toon_and_remove_emit(sheet):
    _open(sheet)
    seen = []
    sheet.choose_toon_requested.connect(lambda: seen.append("choose"))
    sheet.remove_requested.connect(lambda: seen.append("remove"))
    sheet.choose_button.click()
    sheet.remove_button.click()
    assert seen == ["choose", "remove"]


def test_remove_button_names_the_account(sheet):
    _open(sheet)
    assert sheet.remove_button.text().startswith(TRASH_GLYPH)
    assert sheet.remove_button.text().endswith("Remove Gag alt from the launcher")
    _open(sheet, draft=_draft(label=""))
    assert sheet.remove_button.text().endswith("Remove flossbud from the launcher")


# ── pure copy ───────────────────────────────────────────────────────────────

def test_copy_helpers_are_the_handoff_strings():
    d = _draft()
    assert title_for(d) == "Account · Gag alt"
    assert title_for(_draft(label="")) == "Account · flossbud"
    assert subtitle_for(d) == "Toontown Rewritten · changes apply to this account only"
    assert subtitle_for(_draft(game="cc")) == "Corporate Clash · changes apply to this account only"
    assert note_for(0) == "No toons discovered yet"
    assert note_for(3) == "3 toons discovered"
    assert frow_sub_for(3) == "3 discovered"
    assert frow_sub_for(0) == "play once to discover"
    assert remove_label_for(d) == "Remove Gag alt from the launcher"


def test_an_unknown_game_code_subtitles_rather_than_raising():
    """GAME_NAMES is keyed by the two codes the launcher ships; a third would
    have taken the header out with a KeyError."""
    assert subtitle_for(_draft(game="xx")) == (
        "XX · changes apply to this account only")
    assert subtitle_for(_draft(game="")) == (
        " · changes apply to this account only")


# ── live preview (spec §3) ──────────────────────────────────────────────────

def test_preview_follows_the_label_and_username_as_typed(sheet):
    _open(sheet, toons=[], primary=None)        # no toon: the card shows the label
    sheet.label_input.setText("Main")
    assert sheet.preview.name_text() == "Main"
    assert sheet.preview_entry().label == "Main"
    sheet.username_input.setText("floss")
    assert sheet.preview.user_text() == "floss"
    sheet.label_input.setText("")
    assert sheet.preview.name_text() == "floss"      # display_name falls back


def test_preview_keeps_the_toon_name_while_the_label_changes(sheet):
    _open(sheet)
    sheet.label_input.setText("Main")
    assert sheet.preview.name_text() == "Flossbud"
    assert sheet.preview_entry().label == "Main"


def test_typing_never_rebuilds_the_whole_preview_card(sheet, monkeypatch):
    """Whole-branch review I5: set_entry() reloads the portrait and reparses
    five stylesheets. Only the label and the username can change while
    typing, so the keystroke path must not go through it — while the text it
    does own still tracks every character."""
    rebuilds = []
    real = RosterCard.set_entry

    def counting(card, entry):
        rebuilds.append(entry.display_name)
        real(card, entry)

    monkeypatch.setattr(RosterCard, "set_entry", counting)
    _open(sheet, toons=[], primary=None)     # no toon: the card shows the text
    assert len(rebuilds) == 1                # the open builds it, once
    for n in range(1, 6):
        sheet.label_input.setText("Alpha"[:n])
        assert sheet.preview.name_text() == "Alpha"[:n]
    sheet.username_input.setText("floss")
    assert sheet.preview.user_text() == "floss"
    assert len(rebuilds) == 1                # six keystrokes, no rebuild
    assert sheet.preview_entry().label == "Alpha"


def test_typing_never_re_reads_the_portrait(sheet, render_cache, monkeypatch):
    """The cost I5 names: on a cold toon set_entry's portrait read is about
    four manifest reads through pixmap_for, per character."""
    facade, store, _pf = render_cache
    store.note_dna("ttr", "Flossbud", "7400")
    reads = []
    real = type(facade).pixmap_for

    def counting(self, game, name, pose):
        reads.append((game, name, pose))
        return real(self, game, name, pose)

    monkeypatch.setattr(type(facade), "pixmap_for", counting)
    _open(sheet)
    at_open = len(reads)
    assert at_open >= 1                      # the open really does read
    for n in range(1, 6):
        sheet.label_input.setText("Alpha"[:n])
    assert len(reads) == at_open             # five keystrokes, no re-read
    assert sheet.preview_entry().label == "Alpha"
    assert sheet.preview.name_text() == "Flossbud"     # the toon still wins


def test_a_state_change_survives_a_later_edit(sheet):
    _open(sheet, base=_entry())
    sheet.set_account_state("running")
    sheet.label_input.setText("Main")
    assert sheet.preview.state() == "running"
    assert sheet.preview.footer_text() == "Running"


# ── inline errors (spec §4, handoff §4.4) ───────────────────────────────────

def _red(is_dark=True):
    return gp.sheet_input(True, is_dark)["error"].name(QColor.HexArgb)


def test_show_errors_paints_the_message_and_the_red_border(sheet):
    _open(sheet)
    sheet.show_errors({"username": USERNAME_REQUIRED, "password": PASSWORD_REQUIRED})
    assert sheet.username_error.isVisibleTo(sheet) is True
    assert sheet.username_error.text() == "Username is required"
    assert sheet.password_error.isVisibleTo(sheet) is True
    assert sheet.password_error.text() == "Password is required"
    assert _red() in sheet.username_input.styleSheet()
    assert _red() in sheet.password_input.styleSheet()
    assert _red() not in sheet.label_input.styleSheet()
    assert sheet.errors() == {"username": USERNAME_REQUIRED,
                              "password": PASSWORD_REQUIRED}


def test_editing_a_field_clears_only_its_error(sheet):
    _open(sheet)
    sheet.show_errors({"username": USERNAME_REQUIRED, "password": PASSWORD_REQUIRED})
    sheet.username_input.setText("floss")
    assert sheet.username_error.isVisibleTo(sheet) is False
    assert sheet.password_error.isVisibleTo(sheet) is True
    assert sheet.errors() == {"password": PASSWORD_REQUIRED}
    assert _red() not in sheet.username_input.styleSheet()
    assert _red() in sheet.password_input.styleSheet()


def test_clear_errors_and_reopen_reset(sheet):
    _open(sheet)
    sheet.show_errors({"username": USERNAME_REQUIRED})
    sheet.clear_errors()
    assert sheet.errors() == {}
    assert sheet.username_error.isVisibleTo(sheet) is False
    assert _red() not in sheet.username_input.styleSheet()
    sheet.show_errors({"username": USERNAME_REQUIRED})
    _open(sheet)
    assert sheet.errors() == {}
    assert sheet.username_error.isVisibleTo(sheet) is False


def test_a_theme_change_keeps_the_error_border(sheet):
    _open(sheet)
    sheet.show_errors({"username": USERNAME_REQUIRED})
    sheet.apply_theme(False)
    assert _red(False) in sheet.username_input.styleSheet()
    assert sheet.username_error.isVisibleTo(sheet) is True


# ── add mode (spec §1, §2) ──────────────────────────────────────────────────

def test_add_mode_hides_the_danger_zone_and_shows_a_nameless_card(sheet):
    _open(sheet, draft=_draft(MODE_ADD, label="", username="", password=""),
          toons=[], primary=None)
    assert sheet.is_open() is True
    assert sheet.account_id() == ""
    assert sheet.danger_field.isVisibleTo(sheet) is False
    assert sheet.choose_button.isEnabled() is False
    e = sheet.preview_entry()
    assert (e.account_id, e.display_name, e.toon_name) == ("", "", None)
    assert sheet.preview.name_text() == ""
    # Edit mode restores both.
    _open(sheet)
    assert sheet.danger_field.isVisibleTo(sheet) is True
    assert sheet.choose_button.isEnabled() is True


# ── the toon row's portrait + the rename merge (spec §3, handoff §4.4) ──────

def _pixel(pm):
    return pm.toImage().pixelColor(1, 1)


def test_frow_merges_rename_ghosts_in_the_count(sheet):
    """Katsuro is Blue Cat renamed: one toon, counted once, newest name."""
    _open(sheet, toons=[_rec("Katsuro", "7400"), _rec("Blue Cat", "7400"),
                        _rec("Pepper", "7401")], primary=None)
    assert sheet.toon_count() == 2
    assert sheet.frow_sub_text() == "2 discovered"
    assert sheet.frow_name_text() == "Katsuro"
    assert sheet.preview.name_text() == "Katsuro"


def test_cc_records_never_merge_in_the_row(sheet):
    _open(sheet, draft=_draft(game="cc"),
          toons=[_rec("Hiro", "", "cc", "bear"), _rec("Bonzo", "", "cc", "dog")],
          primary="Bonzo")
    assert sheet.toon_count() == 2
    assert sheet.frow_name_text() == "Bonzo"


def test_frow_portrait_is_44px_and_reads_the_head_from_the_cache(sheet, render_cache):
    _facade, store, _pf = render_cache
    complete_set(store, "ttr", "Flossbud", "7400", "#ff0000")
    _open(sheet)
    p = sheet.frow_portrait
    assert (p.width(), p.height()) == (FROW_PORTRAIT, FROW_PORTRAIT) == (44, 44)
    assert p.pixmap() is not None
    assert _pixel(p.pixmap()) == QColor("#ff0000")
    assert p.toolTip() == ""


def test_frow_portrait_follows_the_primary(sheet, render_cache):
    _facade, store, _pf = render_cache
    complete_set(store, "ttr", "Flossbud", "7400", "#ff0000")
    complete_set(store, "ttr", "Pepper", "7401", "#00ff00")
    _open(sheet, toons=[_rec("Pepper", "7401"), _rec("Flossbud", "7400")],
          primary="Flossbud")
    assert _pixel(sheet.frow_portrait.pixmap()) == QColor("#ff0000")
    sheet.set_toons([_rec("Pepper", "7401"), _rec("Flossbud", "7400")], "Pepper")
    assert _pixel(sheet.frow_portrait.pixmap()) == QColor("#00ff00")
    assert sheet.frow_name_text() == "Pepper"
    assert sheet.preview.name_text() == "Pepper"


def test_a_cold_frow_portrait_says_the_origin_has_not_drawn_it(sheet, render_cache):
    _facade, store, pf = render_cache
    store.note_dna("ttr", "Flossbud", "7400")
    _open(sheet)
    p = sheet.frow_portrait
    assert p.pixmap() is None
    assert p.toolTip() == AWAITING_RENDER_TOOLTIP.format(name="Flossbud")
    complete_set(store, "ttr", "Flossbud", "7400", "#00ff00")
    pf.render_landed.emit("ttr", "Flossbud", "portrait")      # not the head
    assert p.pixmap() is None
    pf.render_landed.emit("ttr", "Flossbud", CARD_POSE)
    assert p.pixmap() is not None
    assert p.toolTip() == ""


def test_a_landing_that_is_not_yet_servable_keeps_the_frow_picture(sheet, render_cache):
    """Mirror of the roster card's rule: a landing only ever adds a file;
    when the store cannot serve it yet the picture on screen stays."""
    facade, store, pf = render_cache
    complete_set(store, "ttr", "Flossbud", "7400", "#ff0000")
    _open(sheet)
    p = sheet.frow_portrait
    assert _pixel(p.pixmap()) == QColor("#ff0000")
    _os.remove(store.path_for("ttr", "Flossbud", "7400", CARD_POSE))
    store.note_dna("ttr", "Flossbud", "dna2")
    real_png(store.path_for("ttr", "Flossbud", "dna2", CARD_POSE), "#00ff00")
    assert store.mark_landed("ttr", "Flossbud", "dna2", CARD_POSE)
    assert facade.pixmap_for("ttr", "Flossbud", CARD_POSE) is None
    pf.render_landed.emit("ttr", "Flossbud", CARD_POSE)
    assert p.pixmap() is not None, "a landing cleared the portrait"
    assert _pixel(p.pixmap()) == QColor("#ff0000")
    complete_set(store, "ttr", "Flossbud", "dna2", "#00ff00")
    pf.set_promoted.emit("ttr", "Flossbud")
    assert _pixel(p.pixmap()) == QColor("#00ff00")


def test_cc_frow_portrait_never_consults_the_cache(sheet, render_cache, monkeypatch):
    facade, store, _pf = render_cache
    complete_set(store, "cc", "Hiro", "7400")
    asked = []
    monkeypatch.setattr(facade, "pixmap_for", lambda *a: asked.append(a))
    _open(sheet, draft=_draft(game="cc"), toons=[_rec("Hiro", "7400", "cc", "bear")],
          primary="Hiro")
    assert asked == []
    assert sheet.frow_portrait.pixmap() is None


def test_frow_portrait_paints_without_raising(sheet, render_cache, qapp):
    """Silhouette path (no render) and empty path (no toon) both paint."""
    _open(sheet)
    sheet.show()
    qapp.processEvents()
    sheet.frow_portrait.repaint()
    _open(sheet, toons=[], primary=None)
    sheet.frow_portrait.repaint()
