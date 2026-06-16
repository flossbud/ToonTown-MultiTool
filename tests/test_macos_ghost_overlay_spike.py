"""Host-runnable tests for the macOS ghost-overlay feasibility spike.
Pure helpers + never-raise guard paths only; native NSWindow success is
operator-validated on the Mac, not here."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import importlib.util

import pytest

_SPIKE = os.path.join(os.path.dirname(__file__), "..", "scripts",
                      "macos_ghost_overlay_spike.py")


def _load_spike():
    spec = importlib.util.spec_from_file_location("macos_ghost_overlay_spike", _SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def qapp_spike():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


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


class _FakeView:
    def __init__(self, window):
        self._window = window
    def window(self):
        return self._window


class _FakeWindow:
    def __init__(self, is_panel=False):
        self.level = None
        self.collection_behavior = None
        self.ignores = None
        self.hides_on_deactivate = None
        self._is_panel = is_panel
    def setLevel_(self, v):
        self.level = v
    def setCollectionBehavior_(self, v):
        self.collection_behavior = v
    def setIgnoresMouseEvents_(self, v):
        self.ignores = v
    def setHidesOnDeactivate_(self, v):
        self.hides_on_deactivate = v


def test_apply_recipe_sets_all_knobs_on_window():
    spike = _load_spike()
    win = _FakeWindow()
    # Inject symbol resolution + panel check so no AppKit is needed on the host.
    res = spike.apply_recipe_to_window(
        win,
        spike.RECIPE_CANDIDATES[0],
        resolve_level=lambda name: 3 if name == "NSFloatingWindowLevel" else -1,
        resolve_behavior=lambda names: sum(1 for _ in names),  # fake bitmask
        is_panel=lambda w: False,
    )
    assert res["ok"] is True
    assert win.level == 3
    assert win.collection_behavior == 2          # two flags -> fake "bitmask" 2
    assert win.ignores is True
    assert win.hides_on_deactivate is None       # not a panel -> not set


def test_apply_recipe_sets_hides_on_deactivate_for_panel():
    spike = _load_spike()
    win = _FakeWindow(is_panel=True)
    res = spike.apply_recipe_to_window(
        win, spike.RECIPE_CANDIDATES[0],
        resolve_level=lambda name: 5,
        resolve_behavior=lambda names: 0,
        is_panel=lambda w: True,
    )
    assert res["ok"] is True
    assert win.hides_on_deactivate is False      # NSPanel -> set False


def test_harden_returns_reason_when_window_nil():
    spike = _load_spike()
    view = _FakeView(window=None)                # view.window() is nil
    res = spike.harden_widget(view_resolver=lambda: view,
                              recipe=spike.RECIPE_CANDIDATES[0])
    assert res["ok"] is False
    assert "window" in res["reason"].lower()


def test_harden_never_raises_on_resolver_exception():
    spike = _load_spike()
    def boom():
        raise RuntimeError("no winId")
    res = spike.harden_widget(view_resolver=boom,
                              recipe=spike.RECIPE_CANDIDATES[0])
    assert res["ok"] is False
    assert "no winId" in res["reason"]


def test_spike_overlay_has_shipped_flags(qapp_spike):
    spike = _load_spike()
    from PySide6.QtCore import Qt
    ov = spike.SpikeOverlay(recipe=spike.RECIPE_CANDIDATES[0])
    try:
        fl = ov.windowFlags()
        assert fl & Qt.WindowTransparentForInput
        assert fl & Qt.WindowStaysOnTopHint
        assert fl & Qt.FramelessWindowHint
        assert fl & Qt.WindowDoesNotAcceptFocus
    finally:
        ov.deleteLater()


def test_spike_overlay_harden_disabled_flag(qapp_spike):
    # --no-harden -> harden_enabled=False: the true fail-open control (overlay
    # shown with ZERO native NSWindow hardening, relying only on Qt's flags).
    spike = _load_spike()
    ov = spike.SpikeOverlay(spike.RECIPE_CANDIDATES[0], harden_enabled=False)
    try:
        assert ov._harden_enabled is False
    finally:
        ov.deleteLater()


def test_anchor_point_center_and_corner():
    spike = _load_spike()
    geom = (100, 200, 800, 600)   # x, y, w, h (points, top-left)
    assert spike.anchor_point(geom, "center") == (500, 500)   # 100+400, 200+300
    assert spike.anchor_point(geom, "corner") == (100, 200)   # top-left
    assert spike.anchor_point(geom, "br") == (900, 800)       # bottom-right


def test_build_parser_accepts_no_harden():
    spike = _load_spike()
    args = spike._build_parser().parse_args(["--no-harden", "--mode", "point"])
    assert args.no_harden is True
    assert spike._build_parser().parse_args(["--mode", "point"]).no_harden is False


def test_show_at_does_not_harden_off_cocoa(qapp_spike):
    # Regression: under offscreen (non-cocoa) on a Mac, sys.platform is 'darwin'
    # but winId() is NOT an NSView -> resolving it through objc would segfault.
    # show_at must skip native hardening on any non-cocoa backend and return.
    spike = _load_spike()
    ov = spike.SpikeOverlay(spike.RECIPE_CANDIDATES[0])
    try:
        ov.show_at(50, 50)          # must NOT crash
        assert ov.isVisible()
    finally:
        ov.hide()
        ov.deleteLater()
