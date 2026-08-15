"""Lineup geometry, diffing, and the reduced-motion snap."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QPixmap

import utils.motion as motion
import utils.widgets.grandstand.crew_lineup as crew_module
from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand.crew_lineup import (
    CAMEO, CREW_SLOTS, ROT, CrewLineup,
)
from utils.widgets.grandstand.model import LineupEntry


def _e(aid, treatment="bust", stem=None, species=None, dna="7400",
       pose="portrait"):
    return LineupEntry(account_id=aid, treatment=treatment, pose=pose,
                       dna=dna, icon_stem=stem, species=species,
                       accent="#4a8fe7", initial=aid[:1].upper())


@pytest.fixture
def crew(qapp, monkeypatch):
    # Exercise the real fetcher integration while isolating its external HTTP
    # boundary. Dedicated tests below inspect requests and deliver replies.
    monkeypatch.setattr(
        RenditionPoseFetcher, "cached_pixmap",
        lambda self, dna, pose: None,
    )
    monkeypatch.setattr(
        RenditionPoseFetcher, "request",
        lambda self, dna, pose: None,
    )
    c = CrewLineup()
    c.resize(500, 232)
    yield c
    c.close()
    c.deleteLater()
    qapp.processEvents()


def test_slot_table_matches_the_handoff():
    """Handoff §8 CREW_SLOTS — the lineup is centred on its own count."""
    assert CREW_SLOTS == {1: [168], 2: [252, 84], 3: [300, 168, 36],
                          4: [336, 224, 112, 0]}
    assert ROT == [-3, 2, -2, 3]


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_each_party_size_uses_its_own_offsets(crew, n):
    crew.set_entries([_e(f"a{i}") for i in range(n)])
    assert [s.target_right for s in crew.slots()] == CREW_SLOTS[n]
    assert [s.right for s in crew.slots()] == CREW_SLOTS[n]
    assert all(slot.is_new is False for slot in crew.slots())


def test_empty_party_has_no_slots(crew):
    crew.set_entries([])
    assert crew.slots() == []


def test_more_than_four_entries_is_truncated(crew):
    crew.set_entries([_e(f"a{i}") for i in range(6)])
    assert len(crew.slots()) == 4


def test_a_surviving_toon_slides_rather_than_jumps(crew):
    crew.set_entries([_e("a"), _e("b")])
    crew.settle()
    first = crew.slot_for("a")
    was = first.right
    crew.set_entries([_e("a"), _e("b"), _e("c")])
    assert crew.slot_for("a") is first          # same object, not rebuilt
    assert first.target_right == CREW_SLOTS[3][0]
    assert first.right == was                   # has NOT jumped there yet
    crew._tick()
    assert was < first.right < first.target_right
    crew.settle()
    assert first.right == pytest.approx(CREW_SLOTS[3][0])


def test_a_survivor_does_not_jump_when_reflow_starts_before_its_first_tick(crew):
    crew.set_entries([_e("a"), _e("b")])
    first = crew.slot_for("a")
    was = first.right

    crew.set_entries([_e("a"), _e("b"), _e("c")])

    assert crew.slot_for("a") is first
    assert first.target_right == CREW_SLOTS[3][0]
    assert first.right == was
    assert first.right != first.target_right


def test_mid_entrance_reflow_keeps_opacity_and_lift_monotonic(crew):
    crew.set_entries([_e("a"), _e("b")])
    first = crew.slot_for("a")
    samples = [(first.opacity, first.lift)]
    for _ in range(5):
        crew._tick()
        samples.append((first.opacity, first.lift))

    crew.set_entries([_e("a"), _e("b"), _e("c")])
    assert crew.slot_for("a") is first
    samples.append((first.opacity, first.lift))
    for _ in range(5):
        crew._tick()
        samples.append((first.opacity, first.lift))

    opacities = [opacity for opacity, _lift in samples]
    lifts = [lift for _opacity, lift in samples]
    assert all(after >= before
               for before, after in zip(opacities, opacities[1:]))
    assert all(after <= before
               for before, after in zip(lifts, lifts[1:]))


def test_a_removed_toon_is_dropped(crew):
    crew.set_entries([_e("a"), _e("b")])
    crew.set_entries([_e("b")])
    assert crew.slot_for("a") is None
    assert [s.account_id for s in crew.slots()] == ["b"]


def test_cameo_slots_carry_their_accent_ring(crew):
    crew.set_entries([_e("a", treatment="cameo", stem="bear")])
    slot = crew.slot_for("a")
    assert slot.treatment == "cameo"
    assert slot.size == (CAMEO, CAMEO)


def test_placeholder_slots_show_an_initial(crew):
    crew.set_entries([_e("zed", treatment="placeholder")])
    assert crew.slot_for("zed").initial == "Z"


def test_reduced_motion_snaps_to_the_end_state(crew, monkeypatch):
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    crew.set_entries([_e("a"), _e("b")])
    for slot in crew.slots():
        assert slot.opacity == 1.0
        assert slot.lift == 0.0
        assert slot.right == slot.target_right


def test_same_account_with_new_dna_keeps_slot_and_requests_fresh_art(
        crew, monkeypatch):
    requests = []
    monkeypatch.setattr(
        RenditionPoseFetcher, "request",
        lambda self, dna, pose: requests.append((dna, pose)),
    )
    crew.set_entries([_e("a", dna="7400")])
    crew.settle()
    first = crew.slot_for("a")
    requests.clear()

    crew.set_entries([_e("a", dna="8500")])

    assert crew.slot_for("a") is first
    assert first.dna == "8500"
    assert requests == [("8500", "portrait")]


def test_same_account_with_new_pose_keeps_slot_and_refreshes_art(
        crew, monkeypatch):
    requests = []
    monkeypatch.setattr(
        RenditionPoseFetcher, "request",
        lambda self, dna, pose: requests.append((dna, pose)),
    )
    crew.set_entries([_e("a", pose="portrait")])
    crew.settle()
    first = crew.slot_for("a")
    requests.clear()

    crew.set_entries([_e("a", pose="portrait-grin")])

    assert crew.slot_for("a") is first
    assert first.pose == "portrait-grin"
    assert (first.opacity, first.lift) == (1.0, 0.0)
    assert requests == [("7400", "portrait-grin")]


def test_same_account_with_new_treatment_keeps_slot_and_refreshes_art(
        crew, monkeypatch):
    requests = []
    monkeypatch.setattr(
        RenditionPoseFetcher, "request",
        lambda self, dna, pose: requests.append((dna, pose)),
    )
    crew.set_entries([_e("a", treatment="bust")])
    crew.settle()
    first = crew.slot_for("a")
    requests.clear()

    crew.set_entries([_e("a", treatment="standing")])

    assert crew.slot_for("a") is first
    assert first.treatment == "standing"
    assert (first.opacity, first.lift) == (1.0, 0.0)
    assert requests == [("7400", "portrait")]


def test_species_only_change_updates_the_retained_fallback_slot(crew):
    crew.set_entries([_e("a", treatment="cameo", species="bear")])
    first = crew.slot_for("a")

    crew.set_entries([_e("a", treatment="cameo", species="dog")])

    assert crew.slot_for("a") is first
    assert first.species == "dog"


def test_cameo_icon_change_keeps_slot_and_replaces_art(crew, monkeypatch):
    bear = QPixmap(2, 2)
    dog = QPixmap(3, 3)
    art = {"bear": bear, "dog": dog}
    monkeypatch.setattr(
        crew_module, "load_race_pixmap", lambda stem: art[stem]
    )
    crew.set_entries([_e("a", treatment="cameo", stem="bear")])
    first = crew.slot_for("a")
    assert first.pixmap is bear

    crew.set_entries([_e("a", treatment="cameo", stem="dog")])

    assert crew.slot_for("a") is first
    assert first.icon_stem == "dog"
    assert first.pixmap is dog


def test_pose_reply_must_match_the_key_the_slot_requested(crew):
    crew.set_entries([_e("a", treatment="bust", dna="7400")])
    first = crew.slot_for("a")

    # The live DNA/pose remain identical, but cameo art does not request a
    # rendition. A late reply for the old bust must therefore be ignored.
    crew.set_entries([
        _e("a", treatment="cameo", stem=None, species="bear", dna="7400")
    ])
    current = crew.slot_for("a")
    assert current is first
    assert current.requested_key is None

    stale = QPixmap(2, 2)
    crew._on_pose_ready("7400", "portrait", stale)

    assert current.pixmap is None


def test_pose_reply_only_updates_a_slot_waiting_for_that_art(crew):
    crew.set_entries([_e("a", dna="7400")])
    slot = crew.slot_for("a")
    ready = QPixmap(2, 2)

    crew._on_pose_ready("stale-dna", "portrait", ready)
    crew._on_pose_ready("7400", "stale-pose", ready)
    assert slot.pixmap is None

    crew._on_pose_ready("7400", "portrait", ready)
    assert slot.pixmap is ready
    assert slot.requested_key is None


def test_paints_without_error_in_every_treatment(crew, qapp):
    crew.set_entries([_e("a", "standing"), _e("b", "bust"),
                      _e("c", "cameo", "missing-race-asset"),
                      _e("d", "placeholder")])
    crew.show()
    qapp.processEvents()
    assert crew.isVisible() is True
    crew.repaint()          # must not raise, including with null pixmaps
