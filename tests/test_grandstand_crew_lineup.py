"""Lineup geometry, diffing, and the reduced-motion snap."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor, QPixmap

import utils.motion as motion
import utils.widgets.grandstand.crew_lineup as crew_module
from tests._render_fixtures import complete_set
from utils.widgets.grandstand.crew_lineup import (
    CAMEO, CREW_SLOTS, ROT, CrewLineup,
)
from utils.widgets.grandstand.model import LineupEntry


def _e(aid, treatment="bust", stem=None, species=None, dna="7400",
       pose="portrait", game="ttr", toon_name=None):
    return LineupEntry(account_id=aid, game=game,
                       toon_name=aid.title() if toon_name is None else toon_name,
                       treatment=treatment, pose=pose,
                       dna=dna, icon_stem=stem, species=species,
                       accent="#4a8fe7", initial=aid[:1].upper())


@pytest.fixture
def crew(qapp, render_cache):
    # The real cache integration, isolated: `render_cache` installs a
    # ToonRenders whose downloads never run. Dedicated tests below put sets
    # on disk and fire the cache's own signals.
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


def _asking(facade, monkeypatch):
    """Record every (game, toon, pose) the lineup asks the cache for."""
    asked = []
    monkeypatch.setattr(facade, "pixmap_for", lambda *a: asked.append(a))
    return asked


def test_same_account_with_new_dna_keeps_slot_and_refreshes_art(
        crew, render_cache, monkeypatch):
    facade, _store, _pf = render_cache
    asked = _asking(facade, monkeypatch)
    crew.set_entries([_e("a", dna="7400")])
    crew.settle()
    first = crew.slot_for("a")
    asked.clear()

    crew.set_entries([_e("a", dna="8500")])

    assert crew.slot_for("a") is first
    assert first.dna == "8500"
    assert asked == [("ttr", "A", "portrait")]


def test_same_account_with_new_toon_name_keeps_slot_and_refreshes_art(
        crew, render_cache, monkeypatch):
    """The cache is keyed by (game, toon); a same-dna entry under another
    name is another toon's folder, so the art must be asked for again."""
    facade, _store, _pf = render_cache
    asked = _asking(facade, monkeypatch)
    crew.set_entries([_e("a", toon_name="Hiro")])
    crew.settle()
    first = crew.slot_for("a")
    asked.clear()

    crew.set_entries([_e("a", toon_name="Blue Cat")])       # same dna, same pose

    assert crew.slot_for("a") is first
    assert first.toon_name == "Blue Cat"
    assert asked == [("ttr", "Blue Cat", "portrait")]


def test_same_account_with_new_game_keeps_slot_and_refreshes_art(
        crew, render_cache, monkeypatch):
    facade, _store, _pf = render_cache
    asked = _asking(facade, monkeypatch)
    crew.set_entries([_e("a", game="ttr")])
    crew.settle()
    first = crew.slot_for("a")
    asked.clear()

    crew.set_entries([_e("a", game="cc")])                   # same dna, same name

    assert crew.slot_for("a") is first
    assert first.game == "cc"
    assert asked == [("cc", "A", "portrait")]


def test_same_account_with_new_pose_keeps_slot_and_refreshes_art(
        crew, render_cache, monkeypatch):
    facade, _store, _pf = render_cache
    asked = _asking(facade, monkeypatch)
    crew.set_entries([_e("a", pose="portrait")])
    crew.settle()
    first = crew.slot_for("a")
    asked.clear()

    crew.set_entries([_e("a", pose="portrait-grin")])

    assert crew.slot_for("a") is first
    assert first.pose == "portrait-grin"
    assert (first.opacity, first.lift) == (1.0, 0.0)
    assert asked == [("ttr", "A", "portrait-grin")]


def test_same_account_with_new_treatment_keeps_slot_and_refreshes_art(
        crew, render_cache, monkeypatch):
    facade, _store, _pf = render_cache
    asked = _asking(facade, monkeypatch)
    crew.set_entries([_e("a", treatment="bust")])
    crew.settle()
    first = crew.slot_for("a")
    asked.clear()

    crew.set_entries([_e("a", treatment="standing")])

    assert crew.slot_for("a") is first
    assert first.treatment == "standing"
    assert (first.opacity, first.lift) == (1.0, 0.0)
    assert asked == [("ttr", "A", "portrait")]


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


def _pixel(pixmap):
    return pixmap.toImage().pixelColor(0, 0)


def test_a_slot_whose_toon_has_a_complete_set_draws_it(crew, render_cache):
    _facade, store, _pf = render_cache
    complete_set(store, "ttr", "A", "7400", "#ff0000")

    crew.set_entries([_e("a")])

    slot = crew.slot_for("a")
    assert slot.pixmap is not None
    assert _pixel(slot.pixmap) == QColor("#ff0000")     # the disk render itself


def test_a_slot_whose_toon_has_nothing_cached_draws_none_and_queues_the_pose(
        crew, render_cache):
    _facade, store, pf = render_cache
    store.note_dna("ttr", "A", "7400")          # discovered, not yet fetched

    crew.set_entries([_e("a", pose="portrait-grin")])

    assert crew.slot_for("a").pixmap is None
    key = ("ttr", "A", "7400", "portrait-grin")
    assert key in pf._queue or key in pf._in_flight        # the want went in


def test_a_landing_never_puts_a_rendition_on_a_cameo_slot(crew, render_cache):
    """The live DNA/pose stay identical across bust -> cameo, but cameo art
    is the race icon, not a rendition. A landing for that toon's pose must
    therefore leave the cameo alone."""
    _facade, store, pf = render_cache
    store.note_dna("ttr", "A", "7400")
    crew.set_entries([_e("a", treatment="bust")])
    first = crew.slot_for("a")
    crew.set_entries([_e("a", treatment="cameo", stem=None, species="bear")])
    assert crew.slot_for("a") is first

    complete_set(store, "ttr", "A", "7400", "#ff0000")
    pf.render_landed.emit("ttr", "A", "portrait")

    assert first.pixmap is None


def test_render_landed_fills_only_the_slot_whose_toon_and_pose_it_is(
        crew, render_cache):
    _facade, store, pf = render_cache
    store.note_dna("ttr", "A", "7400")
    crew.set_entries([_e("a")])                # pose "portrait"
    slot = crew.slot_for("a")
    assert slot.pixmap is None

    complete_set(store, "ttr", "A", "7400", "#00ff00")
    pf.render_landed.emit("ttr", "A", "head")            # not this slot's pose
    pf.render_landed.emit("ttr", "Hiro", "portrait")     # not this slot's toon
    pf.render_landed.emit("cc", "A", "portrait")         # not this slot's game
    assert slot.pixmap is None

    pf.render_landed.emit("ttr", "A", "portrait")
    assert slot.pixmap is not None
    assert _pixel(slot.pixmap) == QColor("#00ff00")


def test_set_promoted_refreshes_the_slot_to_the_new_look(crew, render_cache):
    _facade, store, pf = render_cache
    complete_set(store, "ttr", "A", "old", "#ff0000")
    crew.set_entries([_e("a", dna="old")])
    slot = crew.slot_for("a")
    assert _pixel(slot.pixmap) == QColor("#ff0000")

    complete_set(store, "ttr", "A", "new", "#00ff00")    # promoted on disk
    pf.set_promoted.emit("ttr", "Hiro")                   # someone else's
    assert _pixel(slot.pixmap) == QColor("#ff0000")

    pf.set_promoted.emit("ttr", "A")
    assert _pixel(slot.pixmap) == QColor("#00ff00")


def test_paints_without_error_in_every_treatment(crew, qapp):
    crew.set_entries([_e("a", "standing"), _e("b", "bust"),
                      _e("c", "cameo", "missing-race-asset"),
                      _e("d", "placeholder")])
    crew.show()
    qapp.processEvents()
    assert crew.isVisible() is True
    crew.repaint()          # must not raise, including with null pixmaps


def test_a_landing_that_is_not_yet_servable_keeps_the_picture(crew, render_cache):
    """A landing only ever adds a file. When that file belongs to an outfit
    the store cannot serve yet, the figure on stage is still the best the
    lineup has: it keeps it. Only a promotion replaces it. (The toon keeps a
    complete set here -- with one lost file, so the read genuinely misses --
    because a toon with no complete set at all IS served its candidate.)"""
    from tests._render_fixtures import real_png
    facade, store, pf = render_cache
    complete_set(store, "ttr", "A", "7400", "#ff0000")
    crew.set_entries([_e("a")])                    # pose "portrait"
    slot = crew.slot_for("a")
    assert _pixel(slot.pixmap) == QColor("#ff0000")
    os.remove(store.path_for("ttr", "A", "7400", "portrait"))     # lost; nothing told the lineup
    store.note_dna("ttr", "A", "dna2")             # ...and the toon changed outfit meanwhile
    real_png(store.path_for("ttr", "A", "dna2", "portrait"), "#00ff00")
    assert store.mark_landed("ttr", "A", "dna2", "portrait")
    assert facade.pixmap_for("ttr", "A", "portrait") is None      # landed, not servable
    pf.render_landed.emit("ttr", "A", "portrait")
    assert slot.pixmap is not None, "a landing cleared the figure"
    assert _pixel(slot.pixmap) == QColor("#ff0000")
    complete_set(store, "ttr", "A", "dna2", "#00ff00")
    pf.set_promoted.emit("ttr", "A")
    assert _pixel(slot.pixmap) == QColor("#00ff00")
