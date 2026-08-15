"""Grandstand model: portrait capability, footer copy, lineup slotting."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.recent_toons import ToonRecord
from utils.widgets.grandstand import model as gm


def _entry(aid, *, toon="Flossbud", dna="74000101", species="cat",
           game="ttr", state="idle", is_primary=True, rec_accent=None,
           customization=None):
    rec = None
    if toon is not None:
        rec = ToonRecord(toon, game, dna or "", 100, 140, species, rec_accent)
    return gm.roster_entry(
        account_id=aid, game=game, label=f"L{aid}", username=f"u{aid}",
        rec=rec, entry=customization or {}, state=state, message="", raw_error="",
        is_primary=is_primary)


# ── portrait capability (handoff §4.6) ─────────────────────────────────────

def test_ttr_with_dna_is_render_mode():
    assert gm.portrait_mode("ttr", True) == gm.PORTRAIT_RENDER


def test_ttr_without_dna_is_waiting():
    assert gm.portrait_mode("ttr", False) == gm.PORTRAIT_WAITING


def test_cc_is_always_species_even_with_dna():
    """Corporate Clash publishes no render service, so a dna value on a CC
    account must not promote it to render mode."""
    assert gm.portrait_mode("cc", True) == gm.PORTRAIT_SPECIES
    assert gm.portrait_mode("cc", False) == gm.PORTRAIT_SPECIES


# ── footer copy (handoff §4.1d) ────────────────────────────────

def test_footer_running_beats_everything():
    assert gm.footer_text("running", True, True) == "Running"


def test_footer_without_a_toon():
    assert gm.footer_text("idle", False, False) == "No toon yet"


def test_footer_primary_vs_last_played():
    assert gm.footer_text("idle", True, True) == "Primary"
    assert gm.footer_text("idle", True, False) == "Last played"


# ── roster entries ─────────────────────────────────────────────

def test_roster_entry_carries_identity():
    e = _entry("a")
    assert e.account_id == "a"
    assert e.toon_name == "Flossbud"
    assert e.species == "cat"
    assert e.portrait_mode == gm.PORTRAIT_RENDER
    assert e.footer == "Primary"


def test_roster_entry_without_a_toon_is_waiting():
    e = _entry("a", toon=None)
    assert e.toon_name is None
    assert e.portrait_mode == gm.PORTRAIT_WAITING
    assert e.footer == "No toon yet"


def test_roster_entry_accent_falls_back_to_the_game_accent():
    e = _entry("a")
    assert e.accent.upper() == "#4A8FE7"        # --game-ttr


def test_cc_entry_accent_is_the_cc_game_accent():
    e = _entry("a", game="cc", species="bear")
    assert e.accent.upper() == "#F26D21"


def test_customization_accent_beats_account_accent():
    e = _entry("a", rec_accent="#123456",
               customization={"accent": "#abcdef"})
    assert e.accent == "#abcdef"


def test_account_accent_is_used_without_customization_accent():
    e = _entry("a", rec_accent="#123456")
    assert e.accent == "#123456"


@pytest.mark.parametrize("invalid_accent", ["#zz", "nope", 123])
def test_invalid_customization_accent_falls_through_to_account(invalid_accent):
    e = _entry("a", rec_accent="#123456",
               customization={"accent": invalid_accent})
    assert e.accent == "#123456"


def test_invalid_customization_and_account_accents_fall_through_to_game():
    e = _entry("a", rec_accent="#zz", customization={"accent": "nope"})
    assert e.accent.upper() == "#4A8FE7"


def test_cards_always_use_the_head_pose():
    """Handoff §4.1d: the shelf reads as one uniform row."""
    assert gm.CARD_POSE == "head"


# ── lineup slotting ───────────────────────────────────────────

def test_lineup_follows_the_launch_order():
    entries = [_entry("a"), _entry("b"), _entry("c")]
    out = gm.lineup_entries(entries, ["c", "a", "b"])
    assert [e.account_id for e in out] == ["c", "a", "b"]


def test_lineup_is_capped_at_four_slots():
    entries = [_entry(x) for x in "abcde"]
    out = gm.lineup_entries(entries, list("abcde"))
    assert len(out) == gm.LINEUP_SLOTS == 4


@pytest.mark.parametrize("pose", ["waving", "crying", "cake-topper"])
def test_full_body_pose_stands(pose):
    entries = [_entry("a")]
    standing = gm.lineup_entries(entries, ["a"], poses={"a": pose})
    assert standing[0].treatment == "standing"


def test_bust_pose_does_not_stand():
    entries = [_entry("a")]
    bust = gm.lineup_entries(entries, ["a"], poses={"a": "portrait-grin"})
    assert bust[0].treatment == "bust"


def test_species_account_becomes_a_cameo_with_its_race_icon():
    entries = [_entry("a", game="cc", species="bear")]
    out = gm.lineup_entries(entries, ["a"])
    assert out[0].treatment == "cameo"
    assert out[0].icon_stem == "bear"


def test_toonless_account_becomes_a_placeholder_with_its_initial():
    entries = [_entry("a", toon=None)]
    out = gm.lineup_entries(entries, ["a"])
    assert out[0].treatment == "placeholder"
    assert out[0].initial == "L"                # from label "La"


def test_a_toonless_account_never_pushes_a_render_off_the_stage():
    """README Q7: it takes a slot only when one is spare."""
    entries = [_entry(x) for x in "abcd"] + [_entry("e", toon=None)]
    out = gm.lineup_entries(entries, list("abcde"))
    assert [e.account_id for e in out] == ["a", "b", "c", "d"]
    assert all(e.treatment != "placeholder" for e in out)


def test_a_toonless_account_takes_a_spare_slot():
    entries = [_entry("a"), _entry("b", toon=None)]
    out = gm.lineup_entries(entries, ["a", "b"])
    assert [e.treatment for e in out] == ["bust", "placeholder"]


def test_unknown_species_has_no_icon_stem():
    entries = [_entry("a", game="cc", species="wombat")]
    out = gm.lineup_entries(entries, ["a"])
    assert out[0].icon_stem is None             # widget falls back to silhouette
    assert out[0].treatment == "cameo"


def test_ids_absent_from_the_entry_list_are_skipped():
    out = gm.lineup_entries([_entry("a")], ["ghost", "a"])
    assert [e.account_id for e in out] == ["a"]
