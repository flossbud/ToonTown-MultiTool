"""Per-toon render store: layout, promotion at 13/13, lookup order, invalidate."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import json

import pytest

from utils.toon_render_store import PNG_SIGNATURE, ToonRenderStore

POSES = ("portrait", "head", "waving")          # a 3-pose contract keeps tests short
DNA1 = "74000101aa"
DNA2 = "74000101bb"


def _png(path: str, tag: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(PNG_SIGNATURE + tag)


@pytest.fixture
def store(tmp_path):
    return ToonRenderStore(str(tmp_path), poses=POSES)


def _land_all(store, game, name, dna):
    for pose in POSES:
        _png(store.path_for(game, name, dna, pose))
        assert store.mark_landed(game, name, dna, pose) is True


def test_layout_is_one_folder_per_toon_with_a_dna_subfolder(store, tmp_path):
    p = store.path_for("ttr", "Blue Cat", DNA1, "head")
    assert p == os.path.join(str(tmp_path), "toons", "ttr", "blue-cat", DNA1, "head.png")
    assert os.path.isdir(os.path.dirname(p))


def test_slug_collisions_get_a_suffix_and_the_manifest_keeps_the_real_name(store):
    a = store.toon_dir("ttr", "Blue Cat")
    b = store.toon_dir("ttr", "blue cat")
    assert a != b
    with open(os.path.join(b, "manifest.json")) as f:
        assert json.load(f)["name"] == "blue cat"


def test_a_new_dna_is_a_candidate_not_current(store):
    assert store.note_dna("ttr", "Hiro", DNA1) == "candidate"
    assert store.current_dna("ttr", "Hiro") is None
    assert store.candidate_dna("ttr", "Hiro") == DNA1
    assert store.lookup("ttr", "Hiro", "head") is None


def test_missing_poses_is_the_whole_set_for_a_new_dna(store):
    store.note_dna("ttr", "Hiro", DNA1)
    assert store.missing_poses("ttr", "Hiro", DNA1) == list(POSES)


def test_promotion_needs_every_pose(store):
    store.note_dna("ttr", "Hiro", DNA1)
    _png(store.path_for("ttr", "Hiro", DNA1, "portrait"))
    store.mark_landed("ttr", "Hiro", DNA1, "portrait")
    assert store.promote_if_complete("ttr", "Hiro") is False
    assert store.lookup("ttr", "Hiro", "portrait") is None     # candidate never serves
    _land_all(store, "ttr", "Hiro", DNA1)
    assert store.promote_if_complete("ttr", "Hiro") is True
    assert store.current_dna("ttr", "Hiro") == DNA1
    assert store.candidate_dna("ttr", "Hiro") is None
    path, tier = store.lookup("ttr", "Hiro", "head")
    assert tier == "current" and path.endswith(os.path.join(DNA1, "head.png"))


def test_a_file_without_a_png_signature_does_not_count(store):
    store.note_dna("ttr", "Hiro", DNA1)
    for pose in POSES:
        _png(store.path_for("ttr", "Hiro", DNA1, pose))
    bad = store.path_for("ttr", "Hiro", DNA1, "head")
    with open(bad, "wb") as f:
        f.write(b"not a png at all")
    assert store.mark_landed("ttr", "Hiro", DNA1, "head") is False
    for pose in POSES:
        store.mark_landed("ttr", "Hiro", DNA1, pose)
    assert store.promote_if_complete("ttr", "Hiro") is False
    assert "head" in store.missing_poses("ttr", "Hiro", DNA1)


def test_new_outfit_keeps_serving_the_old_set_until_the_new_one_is_whole(store):
    store.note_dna("ttr", "Hiro", DNA1)
    _land_all(store, "ttr", "Hiro", DNA1)
    store.promote_if_complete("ttr", "Hiro")
    assert store.note_dna("ttr", "Hiro", DNA2) == "candidate"
    _png(store.path_for("ttr", "Hiro", DNA2, "head"))
    store.mark_landed("ttr", "Hiro", DNA2, "head")
    path, tier = store.lookup("ttr", "Hiro", "head")
    assert tier == "current" and DNA1 in path          # still the old outfit
    _land_all(store, "ttr", "Hiro", DNA2)
    assert store.promote_if_complete("ttr", "Hiro") is True
    path, tier = store.lookup("ttr", "Hiro", "head")
    assert tier == "current" and DNA2 in path
    assert os.path.isdir(os.path.join(store.toon_dir("ttr", "Hiro"), DNA1))   # kept as previous


def test_a_third_outfit_deletes_the_oldest_set(store):
    for dna in (DNA1, DNA2, "74000101cc"):
        store.note_dna("ttr", "Hiro", dna)
        _land_all(store, "ttr", "Hiro", dna)
        assert store.promote_if_complete("ttr", "Hiro") is True
    d = store.toon_dir("ttr", "Hiro")
    assert not os.path.isdir(os.path.join(d, DNA1))
    assert os.path.isdir(os.path.join(d, DNA2))
    assert os.path.isdir(os.path.join(d, "74000101cc"))


def test_lookup_falls_back_to_previous_when_current_lacks_the_pose(store):
    store.note_dna("ttr", "Hiro", DNA1)
    _land_all(store, "ttr", "Hiro", DNA1)
    store.promote_if_complete("ttr", "Hiro")
    store.note_dna("ttr", "Hiro", DNA2)
    _land_all(store, "ttr", "Hiro", DNA2)
    store.promote_if_complete("ttr", "Hiro")
    os.remove(store.path_for("ttr", "Hiro", DNA2, "waving"))   # a lost file
    path, tier = store.lookup("ttr", "Hiro", "waving")
    assert tier == "previous" and DNA1 in path


def test_switching_back_to_the_previous_outfit_restores_it_without_downloads(store):
    store.note_dna("ttr", "Hiro", DNA1)
    _land_all(store, "ttr", "Hiro", DNA1)
    store.promote_if_complete("ttr", "Hiro")
    store.note_dna("ttr", "Hiro", DNA2)
    _land_all(store, "ttr", "Hiro", DNA2)
    store.promote_if_complete("ttr", "Hiro")
    assert store.note_dna("ttr", "Hiro", DNA1) == "current"     # swapped back, instantly
    assert store.current_dna("ttr", "Hiro") == DNA1
    assert store.missing_poses("ttr", "Hiro", DNA1) == []


def test_failed_poses_are_not_missing(store):
    store.note_dna("ttr", "Hiro", DNA1)
    store.mark_failed("ttr", "Hiro", DNA1, "waving")
    assert store.missing_poses("ttr", "Hiro", DNA1) == ["portrait", "head"]


def test_invalidate_drops_current_only_and_requeues_it(store):
    store.note_dna("ttr", "Hiro", DNA1)
    _land_all(store, "ttr", "Hiro", DNA1)
    store.promote_if_complete("ttr", "Hiro")
    store.note_dna("ttr", "Hiro", DNA2)
    _land_all(store, "ttr", "Hiro", DNA2)
    store.promote_if_complete("ttr", "Hiro")
    assert store.invalidate("ttr", "Hiro") == DNA2
    assert store.candidate_dna("ttr", "Hiro") == DNA2
    assert store.missing_poses("ttr", "Hiro", DNA2) == list(POSES)
    path, tier = store.lookup("ttr", "Hiro", "head")
    assert tier == "previous" and DNA1 in path


def test_invalidate_with_nothing_current_is_a_noop(store):
    assert store.invalidate("ttr", "Nobody") is None


def test_disk_faults_read_as_not_present(store, tmp_path):
    store.note_dna("ttr", "Hiro", DNA1)
    _land_all(store, "ttr", "Hiro", DNA1)
    store.promote_if_complete("ttr", "Hiro")
    os.remove(store.path_for("ttr", "Hiro", DNA1, "head"))
    assert store.lookup("ttr", "Hiro", "head") is None
    assert "head" in store.missing_poses("ttr", "Hiro", DNA1)
