"""Host-runnable tests for the macOS ghost-overlay feasibility spike.
Pure helpers + never-raise guard paths only; native NSWindow success is
operator-validated on the Mac, not here."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import importlib.util

_SPIKE = os.path.join(os.path.dirname(__file__), "..", "scripts",
                      "macos_ghost_overlay_spike.py")


def _load_spike():
    spec = importlib.util.spec_from_file_location("macos_ghost_overlay_spike", _SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_coordinate_readout_identity_is_zero_error():
    spike = _load_spike()
    r = spike.coordinate_readout(
        emitted=(800, 600), qt_global=(800, 600), overlay_origin=(799, 597))
    assert r["emitted_vs_qt_delta"] == (0, 0)
    assert r["expected_origin"] == (799, 597)   # qt_global minus hotspot (1, 3)
    assert r["origin_error"] == (0, 0)


def test_coordinate_readout_reports_nonzero_deltas():
    spike = _load_spike()
    # Qt global differs from emitted by (+2, -5); overlay landed 3px right of expected.
    r = spike.coordinate_readout(
        emitted=(100, 200), qt_global=(102, 195), overlay_origin=(104, 192))
    assert r["emitted_vs_qt_delta"] == (2, -5)
    assert r["expected_origin"] == (101, 192)    # (102-1, 195-3)
    assert r["origin_error"] == (3, 0)           # 104-101, 192-192


def test_coordinate_readout_preserves_negative_coordinates():
    spike = _load_spike()
    # Display left-of / above main: negative virtual-desktop coords must pass
    # through untouched (no normalization through a main-display origin).
    r = spike.coordinate_readout(
        emitted=(-1620, -300), qt_global=(-1620, -300), overlay_origin=(-1621, -303))
    assert r["emitted_vs_qt_delta"] == (0, 0)
    assert r["origin_error"] == (0, 0)


def test_recipe_candidates_nonempty_and_indexable():
    spike = _load_spike()
    assert len(spike.RECIPE_CANDIDATES) >= 1
    r0 = spike.RECIPE_CANDIDATES[0]
    # Each recipe is a dict with the four knobs the spike tunes.
    assert set(r0) == {"name", "level_name", "collection_behavior", "ignores_mouse"}
    assert isinstance(r0["collection_behavior"], tuple)


def test_describe_recipe_is_human_readable():
    spike = _load_spike()
    s = spike.describe_recipe(spike.RECIPE_CANDIDATES[0])
    assert spike.RECIPE_CANDIDATES[0]["name"] in s
    assert spike.RECIPE_CANDIDATES[0]["level_name"] in s
