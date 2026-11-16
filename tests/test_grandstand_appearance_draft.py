"""AppearanceDraft: the look being edited (design note §3; handoff §6.2).

The contract that matters most: the draft edits the dict the old customizer
writes, and anything it does not expose survives a Save untouched.
"""
import copy
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor

from utils.rendition_poses import POSE_NAMES
from utils.toon_customization_resolve import (
    resolve_accent, resolve_portrait_brush, resolve_portrait_pattern,
    resolve_portrait_transform, resolve_pose,
)
from utils.toon_pattern_assets import PATTERN_NAMES
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.appearance_draft import (
    DEFAULT_POSE, FILL_GRADIENT, FILL_SOLID, G_ACCENT, G_BACKDROP, G_FRAMING,
    G_PATTERN, G_POSE, PATTERN_CHOICES, POSE_LABELS, AppearanceDraft,
    look_entry, pattern_label,
)

DNA = "74050102013b1b301bb31b12001212010400113800020000016000000000020800"


def _draft(entry=None, *, game="ttr", toon="Flossbud", species="dog", dna=DNA):
    return AppearanceDraft.from_entry(
        account_id="a1", account_name="flossbud", game=game, toon_name=toon,
        species=species, dna=dna, accent_fallback="#4a8fe7", entry=entry or {})


# Everything the old customizer can write for one toon, including the keys
# this editor has no control for.
FULL = {
    "accent": "#e74a4a",
    "body": "#123456",
    "pose": "waving",
    "icon_stem": "bear",
    "portrait": {
        "color": "#4a8fe7",
        "gradient": {"start": "#82a4ff", "end": "#002a97"},
        "pattern": {"name": "hearts", "color": "#ffffff"},
        "transform": {"zoom": 1.4, "offset_x": 0.1, "offset_y": -0.07, "rotate": 12.0},
        "silhouette": {"outline": {"color": "#000000", "width": "thin"},
                       "shadow": {"color": "#111111", "softness": "strong"}},
        "outline": {"color": "#ffffff", "width": "thick"},
    },
    "some_future_key": {"kept": True},
}


# ── seeding: through the resolvers, never around them ───────────────────────

def test_an_empty_entry_seeds_everything_unset():
    d = _draft({})
    assert d.accent is None
    assert d.pose == DEFAULT_POSE
    assert (d.fill, d.color) == (FILL_SOLID, None)
    assert (d.g_start, d.g_end) == gp.DEFAULT_GRADIENT
    assert (d.pat_name, d.pat_color) == (None, gp.DEFAULT_PATTERN_COLOR)
    assert (d.zoom, d.off_x, d.off_y, d.rotate) == (1.0, 0.0, 0.0, 0.0)
    assert d.is_dirty() is False


def test_a_full_entry_seeds_what_the_resolvers_would_paint():
    d = _draft(FULL)
    assert d.accent == resolve_accent(FULL, QColor()).name()
    assert d.pose == resolve_pose(FULL)
    assert d.fill == FILL_GRADIENT                       # gradient beats colour
    assert (d.g_start, d.g_end) == ("#82a4ff", "#002a97")
    assert d.color == "#4a8fe7"                          # kept for a toggle to Solid
    assert (d.pat_name, d.pat_color) == ("hearts", "#ffffff")
    assert (d.zoom, d.off_x, d.off_y, d.rotate) == resolve_portrait_transform(FULL)


@pytest.mark.parametrize("entry", [
    {"accent": "not-a-colour"},
    {"accent": 12},
    {"pose": "portrait-fly"},
    {"portrait": "nonsense"},
    {"portrait": {"gradient": {"start": "#82a4ff"}}},          # half a gradient
    {"portrait": {"pattern": {"name": "dots"}}},               # no colour
    {"portrait": {"transform": {"zoom": 99, "offset_x": -5, "rotate": 540}}},
    {"portrait": {"transform": {"zoom": "big"}}},              # non-numeric
])
def test_invalid_values_read_as_the_resolvers_fallbacks_and_survive_a_save(entry):
    """An entry the resolvers reject is shown as unset, never crashes the
    editor, and is not "repaired" by a Save that changed nothing."""
    d = _draft(entry)
    assert d.is_dirty() is False
    assert d.apply_to(entry) == entry
    assert ZOOM_OK(d.zoom) and -1.0 <= d.off_x <= 1.0 and -180.0 <= d.rotate <= 180.0


def ZOOM_OK(zoom):
    return 0.5 <= zoom <= 3.0


def test_the_draft_never_aliases_the_entry_it_was_seeded_from():
    entry = copy.deepcopy(FULL)
    d = _draft(entry)
    d.base["portrait"]["silhouette"]["outline"]["color"] = "#ffffff"
    assert entry == FULL


# ── the round trip (the hard requirement) ───────────────────────────────────

def test_an_untouched_draft_saves_the_entry_it_was_given():
    d = _draft(FULL)
    assert d.apply_to(FULL) == FULL
    assert d.preview_entry() == FULL


def test_keys_the_editor_does_not_expose_survive_every_edit():
    d = _draft(FULL)
    d.accent = "#56c856"
    d.pose = "head"
    d.fill, d.color = FILL_SOLID, "#e7894a"
    d.pat_name, d.pat_color = "dots", "#1a1d29"
    d.set_framing(zoom=2.0, off_x=0.25, off_y=0.5, rotate=-30)
    out = d.apply_to(FULL)
    assert out["body"] == "#123456"
    assert out["icon_stem"] == "bear"
    assert out["some_future_key"] == {"kept": True}
    assert out["portrait"]["silhouette"] == FULL["portrait"]["silhouette"]
    assert out["portrait"]["outline"] == FULL["portrait"]["outline"]
    # And the five groups landed in the stored schema.
    assert out["accent"] == "#56c856"
    assert out["pose"] == "head"
    assert out["portrait"]["color"] == "#e7894a"
    assert "gradient" not in out["portrait"]
    assert out["portrait"]["pattern"] == {"name": "dots", "color": "#1a1d29"}
    assert out["portrait"]["transform"] == {
        "zoom": 2.0, "offset_x": 0.25, "offset_y": 0.5, "rotate": -30.0}


def test_only_the_changed_group_is_rewritten():
    """An accent edit must not canonicalise the backdrop (which the old
    customizer stored as colour *and* gradient) or anything else."""
    d = _draft(FULL)
    d.accent = "#56c856"
    assert d.changed_groups() == {G_ACCENT}
    expected = copy.deepcopy(FULL)
    expected["accent"] = "#56c856"
    assert d.apply_to(FULL) == expected


def test_save_merges_onto_the_entry_in_the_store_now_not_the_snapshot():
    """A look saved elsewhere while the sheet was open is not clobbered."""
    d = _draft({"accent": "#e74a4a"})
    d.pose = "waving"
    newer = {"accent": "#4ae7d9", "body": "#222222",
             "portrait": {"color": "#56c856"}}
    assert d.apply_to(newer) == {"accent": "#4ae7d9", "body": "#222222",
                                 "pose": "waving",
                                 "portrait": {"color": "#56c856"}}


def test_canonical_forms_match_the_old_customizer():
    """Unset accent, the default pose, no pattern and a neutral transform are
    omitted rather than written as null (handoff §7, overlay handlers)."""
    d = _draft(FULL)
    d.reset()
    out = d.apply_to(FULL)
    assert "accent" not in out and "pose" not in out
    assert set(out["portrait"]) == {"silhouette", "outline"}
    assert out["body"] == "#123456"                       # reset is not a wipe


def test_an_emptied_portrait_is_pruned():
    d = _draft({"portrait": {"color": "#4a8fe7"}})
    d.color = None
    assert d.apply_to({"portrait": {"color": "#4a8fe7"}}) == {}


def test_a_changed_backdrop_is_gradient_or_colour_never_both():
    d = _draft({"portrait": {"color": "#4a8fe7"}})
    d.fill = FILL_GRADIENT
    out = d.apply_to({"portrait": {"color": "#4a8fe7"}})
    assert out == {"portrait": {"gradient": {"start": gp.DEFAULT_GRADIENT[0],
                                             "end": gp.DEFAULT_GRADIENT[1]}}}
    d.fill = FILL_SOLID
    assert d.apply_to({"portrait": {"color": "#4a8fe7"}}) == {
        "portrait": {"color": "#4a8fe7"}}


def test_what_is_saved_is_what_the_resolvers_then_paint():
    d = _draft({})
    d.apply_look(0)                                       # Sky
    d.pose = "portrait-grin"
    d.set_framing(zoom=1.5, off_x=0.2, off_y=-0.1, rotate=15)
    out = d.apply_to({})
    assert resolve_accent(out, QColor()).name() == "#4a8fe7"
    assert resolve_pose(out) == "portrait-grin"
    assert resolve_portrait_brush(out, QColor()).gradient() is not None
    assert resolve_portrait_pattern(out)[0] == "stars"
    assert resolve_portrait_transform(out) == (1.5, 0.2, -0.1, 15.0)


# ── dirty ───────────────────────────────────────────────────────────────────

def test_dirty_follows_the_effective_value_not_the_click_count():
    d = _draft({"portrait": {"color": "#4a8fe7"}})
    d.fill = FILL_GRADIENT
    assert d.changed_groups() == {G_BACKDROP}
    d.fill = FILL_SOLID
    assert d.is_dirty() is False                          # back where it began
    d.pat_name = "dots"
    assert d.changed_groups() == {G_PATTERN}
    d.pat_name = None
    d.pat_color = "#000000"                               # no pattern: colour is moot
    assert d.is_dirty() is False
    d.pose = "head"
    d.set_framing(zoom=1.1)
    assert d.changed_groups() == {G_POSE, G_FRAMING}


def test_a_snapshot_copy_is_independent():
    d = _draft(FULL)
    snap = d.copy()
    d.accent = "#000000"
    d.base["body"] = "#ffffff"
    assert snap.accent == "#e74a4a"
    assert snap.base["body"] == "#123456"
    assert snap.is_dirty() is False and d.is_dirty() is True


# ── framing ─────────────────────────────────────────────────────────────────

def test_framing_is_clamped_to_the_resolvers_ranges():
    d = _draft({})
    d.set_framing(zoom=9, off_x=-4, off_y=4, rotate=400)
    assert (d.zoom, d.off_x, d.off_y, d.rotate) == (3.0, -1.0, 1.0, 180.0)
    d.set_framing(zoom=0.1)
    assert d.zoom == 0.5
    out = d.apply_to({})
    assert resolve_portrait_transform(out) == (0.5, -1.0, 1.0, 180.0)


# ── looks ───────────────────────────────────────────────────────────────────

def test_the_eight_looks_are_the_handoffs():
    assert [look[0] for look in gp.LOOKS] == [
        "Sky", "Sunbeam", "Bubblegum", "Meadow", "Lagoon", "Ember",
        "Midnight", "Slate"]
    assert gp.LOOKS[0][1:] == ("gradient", "#82a4ff", "#002a97", "stars",
                              "#ffffff", "#4a8fe7")
    assert gp.LOOKS[5][1:] == ("gradient", "#e74a4a", "#7a1410", "chevrons",
                              "#e6d35a", "#e74a4a")
    assert gp.LOOKS[7][1:] == ("solid", "#7a7a8a", "#7a7a8a", None,
                              "#ffffff", None)
    assert len(gp.SWATCHES) == 12 and gp.SWATCHES[0] == "#e74a4a"


def test_every_look_uses_a_pattern_the_app_ships():
    for look in gp.LOOKS:
        assert look[4] is None or look[4] in PATTERN_NAMES


@pytest.mark.parametrize("index", range(len(gp.LOOKS)))
def test_applying_a_look_sets_all_five_values_and_lights_it(index):
    d = _draft({})
    d.apply_look(index)
    accent = gp.LOOKS[index][6]
    assert d.matching_look() == index
    out = d.apply_to({})
    assert out == look_entry(index)
    assert out.get("accent") == accent                    # Slate: no key at all


def test_a_look_applied_over_a_stored_look_replaces_all_five_values():
    d = _draft(FULL)
    d.apply_look(6)                                       # Midnight
    out = d.apply_to(FULL)
    assert out["accent"] == "#4a5fe7"
    assert out["portrait"]["gradient"] == {"start": "#4a5fe7", "end": "#1a1d29"}
    assert "color" not in out["portrait"]
    assert out["portrait"]["pattern"] == {"name": "dots", "color": "#ffffff"}
    assert out["pose"] == "waving"                        # a Look is not a pose


def test_a_hand_edit_that_leaves_a_look_unlights_it_and_one_that_lands_relights():
    d = _draft({})
    d.apply_look(1)                                       # Sunbeam
    d.accent = "#000000"
    assert d.matching_look() is None
    d.accent = gp.LOOKS[1][6]
    assert d.matching_look() == 1


# ── pattern chips ───────────────────────────────────────────────────────────

def test_pattern_chips_are_the_handoffs_three():
    assert [key for key, _ in PATTERN_CHOICES] == ["dots", "chevrons", "stars"]
    assert _draft({}).pattern_choices() == list(PATTERN_CHOICES)


def test_a_stored_pattern_outside_the_three_gets_its_own_chip():
    d = _draft(FULL)                                      # hearts
    assert d.pattern_choices()[-1] == ("hearts", "Hearts")
    d.pat_name = "dots"                                   # still offered after a change
    assert ("hearts", "Hearts") in d.pattern_choices()
    assert pattern_label("stripes_diag") == "Stripes diag"


# ── reset and surprise ──────────────────────────────────────────────────────

def test_reset_clears_what_the_editor_exposes_and_nothing_else():
    d = _draft(FULL)
    d.reset()
    assert (d.accent, d.pose, d.fill, d.color, d.pat_name) == (
        None, DEFAULT_POSE, FILL_SOLID, None, None)
    assert (d.zoom, d.off_x, d.off_y, d.rotate) == (1.0, 0.0, 0.0, 0.0)
    assert d.base == FULL


def test_surprise_rolls_a_look_a_bust_pose_and_a_framing_in_render_mode():
    d = _draft({})
    d.surprise(random.Random(7))
    assert d.matching_look() is not None
    assert d.pose in POSE_NAMES[:8]
    assert 1.0 <= d.zoom <= 1.6
    assert abs(d.off_x) <= 0.15 and abs(d.off_y) <= 0.15


def test_surprise_leaves_pose_and_framing_alone_without_a_render():
    """Corporate Clash has no pose and no drawn framing; an account with no
    toon has neither. Only the Look is rolled."""
    for d in (_draft({}, game="cc", toon="Cogsworth", species="DOG", dna=""),
              _draft({}, toon="Nodna", dna="")):
        d.surprise(random.Random(7))
        assert d.matching_look() is not None
        assert d.pose == DEFAULT_POSE
        assert (d.zoom, d.off_x, d.off_y) == (1.0, 0.0, 0.0)


# ── capability (handoff §4.6) ───────────────────────────────────────────────

def test_the_three_portrait_modes():
    assert _draft({}).mode == "render"
    assert _draft({}, game="cc", toon="Cogsworth", species="DOG", dna="").mode == "species"
    assert _draft({}, toon=None, species=None, dna="").mode == "waiting"
    assert _draft({}, toon="Nodna", dna="").mode == "waiting"


def test_capabilities_follow_the_mode():
    render = _draft({})
    assert (render.can_pose, render.can_frame, render.has_toon) == (True, True, True)
    species = _draft({}, game="cc", toon="Cogsworth", species="DOG", dna="")
    assert (species.can_pose, species.can_frame, species.has_toon) == (False, False, True)
    none = _draft({}, toon=None, species=None, dna="")
    assert (none.can_pose, none.can_frame, none.has_toon) == (False, False, False)
    assert none.store_key == "" and render.store_key == "ttr::Flossbud"


def test_the_ring_falls_back_to_the_account_accent():
    d = _draft({})
    assert d.resolved_accent() == "#4a8fe7"
    d.accent = "#e74a4a"
    assert d.resolved_accent() == "#e74a4a"


# ── labels ──────────────────────────────────────────────────────────────────

def test_every_pose_has_a_human_name_and_none_is_the_api_string():
    assert set(POSE_LABELS) == set(POSE_NAMES)
    assert POSE_LABELS["portrait-fall"] == "Falling"
    assert POSE_LABELS["cake-topper"] == "Cake topper"
    assert POSE_LABELS["laffmeter"] == "Laff meter"
    for name, label in POSE_LABELS.items():
        assert "-" not in label and label[0].isupper()
