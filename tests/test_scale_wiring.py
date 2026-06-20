"""Scale-wiring tests for OverlayGroupController (Task 4.2).

These drive a REAL MultitoonTab + real OverlaySurfaces (NoOp backend, so no
Xlib display is opened) through the controller and assert that scrolling the
emblem (set_scale_by_notches) actually:

  * rescales the real card content (apply_metrics -> the live card sizeHint
    shrinks/grows), and
  * reconciles each surface's geometry with that live scaled sizeHint (the
    surface fits the card exactly, NOT the placeholder 300), and
  * debounces: a burst of notches in one event-loop tick collapses into ONE
    apply_metrics at the final scale.

The provider=None path keeps the Task 3.2 behaviour (synchronous, placeholder
geometry, no apply_metrics); the dedicated orchestration coverage lives in
tests/test_group_controller.py.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
        TTMT_CONFIG_DIR=$(mktemp -d) \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_scale_wiring.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.card_metrics import CardMetrics
from utils.overlay.group_controller import OverlayGroupController
from utils.overlay.scale import step_scale
from utils.overlay.surface import CardSurface, EmblemSurface


# ---------------------------------------------------------------------------
# Fixtures / stubs (config + keyring isolated; real card/emblem build path)
# ---------------------------------------------------------------------------
class _FakeWindowManager(QObject):
    """Minimal stand-in for WindowManager (same shape as the other tab tests)."""

    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def get_active_window(self):
        return None

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


class _StubWindow:
    """Records minimize / restore so the controller's window driving is observable."""

    def __init__(self):
        self.calls: list = []

    def showMinimized(self):
        self.calls.append("showMinimized")

    def showNormal(self):
        self.calls.append("showNormal")


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """A fully-built MultitoonTab (real card/emblem build path) under config +
    keyring isolation. Relies on conftest's autouse input_service shutdown."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    # The launch tab probes for CC installs during build; stub it out so the
    # tab build path is hermetic.
    import tabs.launch_tab
    monkeypatch.setattr(tabs.launch_tab, "discover_cc_installs", lambda *a, **k: [])

    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


class _AboveSpyBackend(NoOpOverlayBackend):
    """NoOp backend that records every set_above target (for the topmost re-assert
    coverage on the provider/debounced scale path)."""

    def __init__(self):
        self.above_calls: list = []

    def set_above(self, window):
        self.above_calls.append(window)


class _RealSurfaceFactory:
    """Builds REAL CardSurface/EmblemSurface (NoOp backend)."""

    def __init__(self, backend):
        self._backend = backend
        self.created: list = []

    def __call__(self, state):
        if state.is_emblem:
            surf = EmblemSurface(backend=self._backend)
        else:
            surf = CardSurface(state.surface_id, backend=self._backend)
        self.created.append(surf)
        return surf


def _make(tab=None):
    win = _StubWindow()
    backend = NoOpOverlayBackend()
    factory = _RealSurfaceFactory(backend)
    provider = tab._compact if tab is not None else None
    ctl = OverlayGroupController(
        win, backend=backend, surface_factory=factory, card_provider=provider
    )
    return ctl, factory, win


# ---------------------------------------------------------------------------
# 1. Rescale + surface-size reconciliation
# ---------------------------------------------------------------------------
def test_scale_down_shrinks_cards_and_reconciles_surface_size(qapp, tab):
    compact = tab._compact
    ctl, factory, win = _make(tab)

    assert ctl.enter() is True
    qapp.processEvents()

    # Baseline (scale 1.0): the real card sizeHint, and the surfaces already fit
    # it (no placeholder 300) right out of enter().
    w0, h0 = compact.card_size()
    assert w0 != 300, "card_size must be the REAL sizeHint, not the placeholder"
    for i in range(4):
        geo = ctl._surfaces[i].geometry()
        assert (geo.width(), geo.height()) == (w0, h0), (
            f"card {i} surface must fit the 1.0 sizeHint, got {geo}"
        )

    # Scroll down a few notches -> smaller scale.
    ctl.set_scale_by_notches(-3)
    # Scale updates synchronously even though the recompute is debounced.
    assert ctl._scale == step_scale(1.0, -3)
    assert ctl._scale < 1.0
    # Drive the debounced recompute.
    qapp.processEvents()

    # The real cards actually shrank.
    w1, h1 = compact.card_size()
    assert w1 < w0 and h1 < h0, "the live card content must shrink with scale"

    # Every card surface now fits the SCALED sizeHint exactly (reconciliation).
    for i in range(4):
        geo = ctl._surfaces[i].geometry()
        assert geo.width() == w1, f"card {i} surface width != scaled sizeHint"
        assert geo.height() == h1, f"card {i} surface height != scaled sizeHint"

    # The emblem surface tracks the scaled disc diameter.
    emblem_geo = ctl._surfaces[4].geometry()
    assert emblem_geo.width() == compact.emblem_size()

    ctl.leave()


def test_flush_pending_recompute_is_synchronous(qapp, tab):
    """flush_pending_recompute() applies the debounced recompute without a tick."""
    compact = tab._compact
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()

    ctl.set_scale_by_notches(-2)
    assert ctl._recompute_pending is True
    ctl.flush_pending_recompute()
    assert ctl._recompute_pending is False

    w, h = compact.card_size()
    for i in range(4):
        geo = ctl._surfaces[i].geometry()
        assert (geo.width(), geo.height()) == (w, h)
    ctl.leave()


# ---------------------------------------------------------------------------
# 2. Debounce / coalesce
# ---------------------------------------------------------------------------
def test_rapid_scroll_coalesces_to_one_apply_metrics(qapp, tab):
    compact = tab._compact
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()

    # Spy on apply_metrics (wrapping the real one, so the cards still rescale).
    calls: list = []
    real_apply = compact.apply_metrics

    def spy(metrics):
        calls.append(metrics.scale)
        return real_apply(metrics)

    compact.apply_metrics = spy

    # A rapid burst within one tick.
    ctl.set_scale_by_notches(-1)
    ctl.set_scale_by_notches(-1)
    ctl.set_scale_by_notches(-1)
    assert calls == [], "the recompute must be deferred, not run per notch"

    final = step_scale(step_scale(step_scale(1.0, -1), -1), -1)
    assert ctl._scale == final, "scale updates synchronously to the final value"

    qapp.processEvents()
    assert len(calls) == 1, "the burst must coalesce into ONE apply_metrics"
    assert calls[0] == final, "the single recompute runs at the FINAL scale"

    compact.apply_metrics = real_apply
    ctl.leave()


def test_leave_cancels_pending_recompute(qapp, tab):
    """A pending recompute is cancelled by leave() and never fires after teardown."""
    compact = tab._compact
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()

    calls: list = []
    real_apply = compact.apply_metrics

    def spy(metrics):
        calls.append(metrics.scale)
        return real_apply(metrics)

    compact.apply_metrics = spy

    ctl.set_scale_by_notches(-2)
    assert ctl._recompute_pending is True
    # Tear down BEFORE the tick that would run the recompute.
    ctl.leave()
    assert ctl._recompute_pending is False
    # leave() resets framed (scale-1.0) metrics -> exactly one apply_metrics(1.0),
    # the scaled recompute (the -2 notches) is NOT among them.
    qapp.processEvents()
    assert calls == [1.0], f"only the framed reset must run, got {calls}"

    compact.apply_metrics = real_apply


# ---------------------------------------------------------------------------
# 3. provider=None keeps the Task 3.2 behaviour (synchronous, no debounce)
# ---------------------------------------------------------------------------
def test_provider_none_is_synchronous_no_debounce(qapp):
    from utils.overlay.group_controller import _BASE_CARD_W, _GROUP_GAP, pinwheel_rects

    ctl, factory, win = _make(tab=None)
    assert ctl.enter() is True
    qapp.processEvents()

    before = ctl._scale
    ctl.set_scale_by_notches(1)
    # Synchronous: scale stepped and surfaces re-geometried with NO pending tick.
    assert ctl._scale == step_scale(before, 1)
    assert ctl._recompute_pending is False, "provider=None must not schedule a recompute"

    # Geometry uses the placeholder base sizes (CardMetrics for h/emblem).
    base = CardMetrics(1.0)
    expected = pinwheel_rects(
        ctl._anchor, ctl._scale, _BASE_CARD_W, base.card_min_h, base.emblem, _GROUP_GAP
    )
    for i in range(4):
        assert ctl._surfaces[i].geometry() == expected[i]
    assert ctl._surfaces[4].geometry() == expected["emblem"]

    ctl.leave()


def test_provider_path_reasserts_above_on_scale(qapp, tab):
    """The PRIMARY (provider/debounced) scale path must re-assert ABOVE on every
    surface after the recompute. A regression dropping the reassert in
    _recompute_now() would otherwise go uncaught (the stub-path coverage in
    tests/test_overlay_topmost.py only exercises the provider=None branch)."""
    backend = _AboveSpyBackend()
    factory = _RealSurfaceFactory(backend)
    win = _StubWindow()
    ctl = OverlayGroupController(
        win, backend=backend, surface_factory=factory, card_provider=tab._compact
    )
    assert ctl.enter() is True
    qapp.processEvents()

    backend.above_calls.clear()
    ctl.set_scale_by_notches(-2)          # schedules the debounced recompute
    ctl.flush_pending_recompute()         # run the provider recompute now
    # Every one of the 4 cards + emblem gets ABOVE re-applied after the recompute
    # (the glow surface is also re-asserted, so it is a superset, not exactly 5).
    assert set(ctl._surfaces).issubset(set(backend.above_calls))
    assert len(ctl._surfaces) == 5
    ctl.leave()


def test_cluster_spacing_matches_framed_grid_gap(qapp, tab):
    """The overlay must place cards at the FRAMED grid spacing (grid_gap/2 from
    center), not the spike's loose _GROUP_GAP=24. A regression to the loose gap
    flings the cards far from the emblem (the 'completely offset' bug)."""
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()
    rects = ctl._compute_rects()
    r0, r1 = rects[0], rects[1]
    central_gap = r1.x() - (r0.x() + r0.width())  # between the two top cards
    expected = 2 * round(CardMetrics(ctl._scale).grid_gap / 2)
    assert central_gap == expected, f"central gap {central_gap} != framed {expected}"
    assert central_gap < 40, "must be the tight framed gap, not the loose spike gap (48)"
    ctl.leave()


def test_glow_surface_built_on_enter_and_torn_down_on_leave(qapp, tab):
    """The accent-glow surface (framed-parity halo behind the cluster) is created
    below the cards on enter and destroyed on leave."""
    import shiboken6
    ctl, factory, win = _make(tab)
    assert ctl._glow_surface is None
    ctl.enter()
    qapp.processEvents()
    glow = ctl._glow_surface
    assert glow is not None and ctl._glow_widget is not None
    assert glow.isVisible()
    ctl.leave()
    qapp.processEvents()
    assert ctl._glow_surface is None and ctl._glow_widget is None


def test_reenter_uses_remembered_scale(qapp, tab):
    """A scale-down then leave then re-enter must render at the REMEMBERED overlay
    scale: leave resets the framed cards to 1.0 but self._scale persists, and
    enter() re-applies CardMetrics(self._scale) so the re-entered surfaces match
    the scaled cards (not a 1.0-hint / non-1.0-gap mismatch)."""
    compact = tab._compact
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()
    ctl.set_scale_by_notches(-3)
    qapp.processEvents()
    scaled = ctl._scale
    assert scaled < 1.0
    w_scaled, h_scaled = compact.card_size()
    ctl.leave()
    qapp.processEvents()

    # The remembered overlay scale persists across leave (framed cards reset to 1.0).
    assert ctl._scale == scaled

    ctl.enter()
    qapp.processEvents()
    # Re-enter re-applied the remembered scale: cards are scaled again and every
    # surface is sized consistently from those scaled hints.
    assert compact.card_size() == (w_scaled, h_scaled), "re-enter must restore the scaled card size"
    for i in range(4):
        geo = ctl._surfaces[i].geometry()
        assert (geo.width(), geo.height()) == (w_scaled, h_scaled)
    ctl.leave()


def test_card_size_is_max_across_slots(qapp, tab):
    """card_size() must be the MAX cell sizeHint across all four slots, not slot
    0 - else a slot with a long (eliding) toon name would be clamped/clipped."""
    from PySide6.QtCore import QSize

    compact = tab._compact
    cells = [compact._cells[i]["cell"] for i in range(4)]
    base_w, base_h = compact.card_size()
    # Make slot 2 report a strictly wider sizeHint than the others (mimics a long
    # toon-name eliding label). card_size must pick it up via the max, not slot 0.
    wide = base_w + 200
    cells[2].sizeHint = lambda: QSize(wide, base_h)  # type: ignore[assignment]
    w, h = compact.card_size()
    assert w == wide, "card_size must report the widest slot (max), not slot 0"


def test_overlay_base_card_size_is_framed_1_0(qapp, tab):
    """Base size = uniform card width x card_min_h at scale 1.0 (the framed cell),
    not the looser sizeHint height."""
    from utils.overlay.card_metrics import CardMetrics
    tab._compact.apply_metrics(CardMetrics(1.0))
    qapp.processEvents()
    w, h = tab._compact.overlay_base_card_size()
    assert h == CardMetrics(1.0).card_min_h          # 232, the framed cell height
    assert w == tab._compact.card_size()[0]          # the uniform (max) card width


def test_scale_emblem_sizes_only_the_emblem(qapp, tab):
    """scale_emblem scales the emblem widget (emblem_size grows) WITHOUT touching
    the cards (they must stay at framed 1.0 for the proxy transform)."""
    compact = tab._compact
    base_em = compact.emblem_size()
    card_before = compact.card_size()
    compact.scale_emblem(1.5)
    qapp.processEvents()
    assert compact.emblem_size() > base_em                 # emblem grew
    assert compact.card_size() == card_before              # cards untouched
    compact.scale_emblem(1.0)
