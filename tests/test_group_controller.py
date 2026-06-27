"""Orchestration tests for OverlayGroupController (utils/overlay/group_controller.py).

These exercise the controller's surface LIFECYCLE with STUB surfaces injected via
the surface_factory seam: no real overlay windows, no X11 backend, no QApplication
-bound surfaces.  The controller still needs a QApplication for its primary-screen
anchor default, so the session `qapp` fixture (tests/conftest.py) is requested.

Run:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_group_controller.py tests/test_group_layout.py -q
"""
import pytest
from PySide6.QtGui import QPainterPath

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.card_metrics import CardMetrics
from utils.overlay.group_controller import (
    _BASE_CARD_W,
    _GROUP_GAP,
    OverlayGroupController,
    pinwheel_rects,
)
from utils.overlay.scale import step_scale


# ---------------------------------------------------------------------------
# Stubs: a recording surface + a recording factory + a recording main window
# ---------------------------------------------------------------------------
class _StubSurface:
    """Records every controller-driven call (per-surface and into a shared log)."""

    def __init__(self, key, events: list, fail_method=None):
        self.key = key               # 0-3 for cards, "emblem" for the emblem
        self._events = events        # shared global ordered log of (key, method)
        self.calls: list = []        # per-surface ordered method names + args
        self.geometry = None
        self.shapes: list = []       # list of (path, dpr)
        self._dpr = 1.0
        self._fail_method = fail_method  # raise (after logging) when this is called

    def _log(self, method, arg=None):
        self.calls.append((method, arg))
        self._events.append((self.key, method))
        if method == self._fail_method:
            raise RuntimeError(f"{self.key} boom on {method}")

    def prepare_initial_state(self):
        self._log("prepare_initial_state")

    def set_overlay_geometry(self, rect):
        self.geometry = rect
        self._log("set_overlay_geometry", rect)

    def show(self):
        self._log("show")

    def hide(self):
        self._log("hide")

    def apply_shape(self, path, dpr):
        self.shapes.append((path, dpr))
        self._log("apply_shape", (path, dpr))

    def apply_input_region(self, region):
        # Records the Model-B controls-region path. Unused by these tests (they
        # inject no card_provider, so cards take the apply_shape fallback), but
        # present so a future card_provider test does not hit AttributeError.
        self._log("apply_input_region", region)

    def clear_shape(self):
        self._log("clear_shape")

    def raise_(self):
        self._log("raise_")

    def release(self):
        self._log("release")

    def close(self):
        self._log("close")

    def deleteLater(self):
        self._log("deleteLater")

    def devicePixelRatio(self):
        return self._dpr

    def methods(self):
        return [c[0] for c in self.calls]


class _StubFactory:
    """Builds recording stub surfaces; can be told to raise on the Nth build."""

    def __init__(self, fail_on=None, fail_method=None, fail_method_on=None):
        self.events: list = []       # global ordered (key, method) log
        self.created: list = []      # stub surfaces, in creation order
        self._count = 0
        self._fail_on = fail_on      # 1-based build index at which to raise
        self._fail_method = fail_method      # method name a surface should raise in
        self._fail_method_on = fail_method_on  # 1-based build index that gets fail_method

    def __call__(self, state):
        self._count += 1
        if self._fail_on is not None and self._count == self._fail_on:
            raise RuntimeError(f"factory boom on surface #{self._count}")
        key = "emblem" if state.is_emblem else state.surface_id
        fm = self._fail_method if self._count == self._fail_method_on else None
        surf = _StubSurface(key, self.events, fail_method=fm)
        self.created.append(surf)
        return surf


class _StubWindow:
    """Records minimize / restore so we can assert the controller drives them."""

    def __init__(self):
        self.calls: list = []

    def showMinimized(self):
        self.calls.append("showMinimized")

    def showNormal(self):
        self.calls.append("showNormal")


def _make(fail_on=None, fail_method=None, fail_method_on=None, on_active_changed=None):
    factory = _StubFactory(
        fail_on=fail_on, fail_method=fail_method, fail_method_on=fail_method_on
    )
    win = _StubWindow()
    # NoOp backend so __init__ never opens an Xlib display (X client-slot leak).
    ctl = OverlayGroupController(
        win, backend=NoOpOverlayBackend(), surface_factory=factory,
        on_active_changed=on_active_changed,
    )
    return ctl, factory, win


# ---------------------------------------------------------------------------
# enter()
# ---------------------------------------------------------------------------
class TestEnter:
    def test_builds_five_surfaces_geometried_shaped_shown(self, qapp):
        ctl, factory, win = _make()
        assert ctl.enter() is True
        assert ctl.is_transparent is True
        assert ctl.is_active is True
        assert len(factory.created) == 5
        for surf in factory.created:
            assert surf.geometry is not None, "each surface must be geometried"
            assert len(surf.shapes) == 1, "each surface must be shaped once"
            path, dpr = surf.shapes[0]
            assert isinstance(path, QPainterPath)
            assert isinstance(dpr, float)
            assert "show" in surf.methods(), "each surface must be shown"
            # show() MUST precede apply_shape(): the X11 ShapeInput needs the
            # show()-realized winId, else it is a silent no-op (matches the
            # live-validated spike). Lock the order so it is not "fixed" backwards.
            m = surf.methods()
            assert m.index("show") < m.index("apply_shape")
            # prepare_initial_state() sets the EWMH initial state (skip-taskbar/
            # above) as a property BEFORE the window maps, so it MUST precede show().
            assert "prepare_initial_state" in m
            assert m.index("prepare_initial_state") < m.index("show")

    def test_each_surface_gets_its_pinwheel_rect(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        base = CardMetrics(1.0)
        rects = pinwheel_rects(
            ctl._anchor, 1.0, _BASE_CARD_W, base.card_min_h, base.emblem, _GROUP_GAP
        )
        by_key = {s.key: s for s in factory.created}
        assert set(by_key.keys()) == {0, 1, 2, 3, "emblem"}
        for key, surf in by_key.items():
            assert surf.geometry == rects[key]

    def test_minimizes_main_window_never_hides(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        assert "showMinimized" in win.calls
        assert "hide" not in win.calls  # spec: minimize, never hide

    def test_emblem_shown_last_and_raised_above_cards(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        # The four cards are shown before the emblem.
        show_order = [k for (k, m) in factory.events if m == "show"]
        assert show_order == [0, 1, 2, 3, "emblem"]
        # The emblem is raised, and that raise comes AFTER every card's show.
        raise_idx = factory.events.index(("emblem", "raise_"))
        last_card_show = max(
            i for i, (k, m) in enumerate(factory.events) if m == "show" and k != "emblem"
        )
        assert raise_idx > last_card_show

    def test_open_panel_keeps_panel_above_emblem(self, qapp):
        """With the portable Settings panel open, every emblem raise is followed
        by a panel raise so the emblem never pops over the open panel."""
        ctl, factory, win = _make()
        ctl.enter()
        panel = _StubSurface("panel", factory.events)
        ctl._panel_surface = panel
        factory.events.clear()
        ctl._raise_emblem()
        raises = [k for (k, m) in factory.events if m == "raise_"]
        assert raises == ["emblem", "panel"], raises

    def test_no_panel_leaves_emblem_on_top(self, qapp):
        """Without a panel open the emblem stays the topmost surface (no regression)."""
        ctl, factory, win = _make()
        ctl.enter()
        factory.events.clear()
        ctl._raise_emblem()
        raises = [k for (k, m) in factory.events if m == "raise_"]
        assert raises == ["emblem"], raises


# ---------------------------------------------------------------------------
# set_scale_by_notches()
# ---------------------------------------------------------------------------
class TestScale:
    def test_increases_scale_and_re_geometries_and_re_shapes(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        before = ctl._scale
        for s in factory.created:
            s.calls.clear()
            s.shapes.clear()
        ctl.set_scale_by_notches(1)
        assert ctl._scale == step_scale(before, 1)
        assert ctl._scale > before
        for s in factory.created:
            assert "set_overlay_geometry" in s.methods()
            assert len(s.shapes) == 1, "rescale must re-apply the shape"

    def test_noop_when_framed(self, qapp):
        ctl, factory, win = _make()
        ctl.set_scale_by_notches(1)  # must not raise
        assert factory.created == []
        assert ctl.is_active is False


# ---------------------------------------------------------------------------
# move_group()
# ---------------------------------------------------------------------------
class TestMove:
    def test_shifts_anchor_and_repositions_without_reshape(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        ax, ay = ctl._anchor
        for s in factory.created:
            s.calls.clear()
            s.shapes.clear()
            s.geometry = None
        ctl.move_group(40, -25)
        assert ctl._anchor == (ax + 40, ay - 25)
        for s in factory.created:
            assert s.geometry is not None, "surfaces must be repositioned"
            assert s.shapes == [], "move must not reshape (size unchanged)"
        # Emblem re-raised: once on enter, once on move.
        emblem_raises = [e for e in factory.events if e == ("emblem", "raise_")]
        assert len(emblem_raises) >= 2

    def test_noop_when_framed(self, qapp):
        ctl, factory, win = _make()
        ctl.move_group(10, 10)  # must not raise
        assert factory.created == []
        assert ctl.is_active is False


# ---------------------------------------------------------------------------
# leave()
# ---------------------------------------------------------------------------
class TestLeave:
    def test_releases_then_closes_each_surface_and_restores_window(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        created = list(factory.created)
        ctl.leave()
        assert ctl.is_transparent is False
        assert ctl.is_active is False
        assert ctl._surfaces == [], "no surface may leak into the controller"
        assert "showNormal" in win.calls
        for s in created:
            names = s.methods()
            assert "release" in names and "close" in names
            assert names.index("release") < names.index("close"), "release MUST precede close"

    def test_noop_when_framed(self, qapp):
        ctl, factory, win = _make()
        ctl.leave()  # must not raise
        assert win.calls == []


# ---------------------------------------------------------------------------
# toggle()
# ---------------------------------------------------------------------------
def test_toggle_enters_then_leaves(qapp):
    ctl, factory, win = _make()
    assert ctl.toggle() is True
    assert ctl.is_active is True
    assert ctl.toggle() is False
    assert ctl.is_active is False


# ---------------------------------------------------------------------------
# FAIL-CLOSED transaction (spec section 5)
# ---------------------------------------------------------------------------
def test_enter_is_fail_closed_when_factory_raises_on_third_surface(qapp):
    ctl, factory, win = _make(fail_on=3)
    ok = ctl.enter()
    # Stays Framed.
    assert ok is False
    assert ctl.is_transparent is False
    assert ctl.is_active is False
    assert ctl._surfaces == [], "no half-built overlay may leak"
    # The two surfaces created before the failure are torn down (released + closed).
    assert len(factory.created) == 2
    for s in factory.created:
        names = s.methods()
        assert "release" in names and "close" in names
        assert names.index("release") < names.index("close")
    # Main window untouched: never minimized, so nothing to restore.
    assert win.calls == []


# ---------------------------------------------------------------------------
# Failure paths beyond the factory (post-creation enter failure + throwing leave)
# ---------------------------------------------------------------------------
class TestFailurePaths:
    def test_enter_fail_closed_when_show_raises_midway(self, qapp):
        # The 3rd built surface raises in show() (post-creation, not factory).
        ctl, factory, win = _make(fail_method="show", fail_method_on=3)
        assert ctl.enter() is False
        assert ctl.is_transparent is False
        assert ctl._surfaces == []
        # All 3 created surfaces are torn down (release before close).
        assert len(factory.created) == 3
        for s in factory.created:
            names = s.methods()
            assert "release" in names and "close" in names
            assert names.index("release") < names.index("close")
        # Never reached the minimize step -> nothing to restore.
        assert "showMinimized" not in win.calls

    @pytest.mark.parametrize("method,on", [
        ("set_overlay_geometry", 1),
        ("apply_shape", 1),
        ("raise_", 5),   # emblem raise_() (after all 5 built, before minimize)
    ])
    def test_enter_fail_closed_when_step_raises(self, qapp, method, on):
        ctl, factory, win = _make(fail_method=method, fail_method_on=on)
        assert ctl.enter() is False
        assert ctl.is_transparent is False
        assert ctl._surfaces == []
        # Every created surface is FULLY torn down (hide -> release -> close);
        # release succeeds for these stubs (the failing method is geometry/shape/
        # raise_, not release), so close must run. Positive assertions so an impl
        # that skipped _teardown would fail.
        assert len(factory.created) >= 1
        for s in factory.created:
            names = s.methods()
            assert "hide" in names and "release" in names and "close" in names
            assert names.index("release") < names.index("close")
        # All these steps fail before the minimize, so the window is untouched.
        assert "showMinimized" not in win.calls

    def test_enter_fail_closed_restores_window_if_minimize_raises(self, qapp):
        # showMinimized() raising must still leave the controller Framed + restored.
        ctl, factory, win = _make()

        def boom():
            win.calls.append("showMinimized")
            raise RuntimeError("minimize boom")

        win.showMinimized = boom
        assert ctl.enter() is False
        assert ctl.is_transparent is False
        assert ctl._surfaces == []
        # All 5 surfaces FULLY torn down (hide -> release -> close), and the
        # window restore was attempted.
        assert len(factory.created) == 5
        for s in factory.created:
            names = s.methods()
            assert "hide" in names and "release" in names and "close" in names
            assert names.index("release") < names.index("close")
        assert "showNormal" in win.calls

    def test_leave_protects_card_when_release_raises_and_tears_down_rest(self, qapp):
        # A surface whose release() throws must NOT be close()d/deleteLater()d
        # (destroying it could delete the still-hosted borrowed card, Task 4.1b),
        # but the OTHER surfaces are still fully torn down and the window restored.
        ctl, factory, win = _make(fail_method="release", fail_method_on=2)
        assert ctl.enter() is True
        ctl.leave()
        assert ctl.is_transparent is False
        assert ctl._surfaces == []
        protected = factory.created[1]  # build #2: release raised
        assert "close" not in protected.methods(), "must not destroy a non-released surface"
        assert "deleteLater" not in protected.methods()
        # The controller RETAINS a reference so Python GC cannot destroy the
        # parentless surface (and delete its still-hosted card).
        assert protected in ctl._orphans
        for s in factory.created:
            if s is protected:
                continue
            assert "close" in s.methods()  # others fully torn down
        assert "showNormal" in win.calls


# ---------------------------------------------------------------------------
# update_shapes + enter-while-active no-op
# ---------------------------------------------------------------------------
class TestMisc:
    def test_update_shapes_replaces_and_reshapes_all(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        for s in factory.created:
            s.calls.clear()
            s.shapes.clear()
            s.geometry = None
        ctl.update_shapes()
        for s in factory.created:
            # Full re-layout: geometry AND shape re-applied (monitor change can
            # move a surface, not just change its dpr).
            assert s.geometry is not None, "update_shapes must re-apply geometry"
            assert len(s.shapes) == 1, "update_shapes must re-apply the shape"
        # Emblem re-raised after the re-layout.
        assert factory.created[-1].key == "emblem"
        assert "raise_" in factory.created[-1].methods()

    def test_update_shapes_noop_when_framed(self, qapp):
        ctl, factory, win = _make()
        ctl.update_shapes()  # not active
        assert factory.created == []

    def test_enter_while_active_is_noop_true(self, qapp):
        ctl, factory, win = _make()
        assert ctl.enter() is True
        n = len(factory.created)
        assert ctl.enter() is True          # second enter: no-op
        assert len(factory.created) == n    # no new surfaces built


# ---------------------------------------------------------------------------
# on_active_changed callback (tab learns when the overlay goes up/down)
# ---------------------------------------------------------------------------
class TestActiveChangedCallback:
    def test_fires_true_on_enter_then_false_on_leave(self, qapp):
        seen: list = []
        ctl, factory, win = _make(on_active_changed=seen.append)
        assert ctl.enter() is True
        assert seen == [True], "enter-success must report active=True after setup"
        ctl.leave()
        assert seen == [True, False], "leave must report active=False after teardown"

    def test_not_fired_on_failed_enter(self, qapp):
        # A fail-closed enter stays Framed: it never went active, so no transition.
        seen: list = []
        ctl, factory, win = _make(fail_on=1, on_active_changed=seen.append)
        assert ctl.enter() is False
        assert seen == []

    def test_observer_error_does_not_break_enter(self, qapp):
        def _boom(_active):
            raise RuntimeError("observer blew up")
        ctl, factory, win = _make(on_active_changed=_boom)
        # Best-effort: a raising observer must not corrupt enter/leave.
        assert ctl.enter() is True
        ctl.leave()
        assert ctl.is_active is False


# ---------------------------------------------------------------------------
# Radial dim backdrop (its own layer, BELOW the emblem)
# ---------------------------------------------------------------------------
class TestRadialDim:
    def test_restack_orders_dim_below_radial(self, qapp):
        """_restack_radial_layers raises dim first (lowest of the trio) then the
        radial last (top), so the emblem (raised between them) ends up in front of
        the dim but behind the radial."""
        ctl, factory, win = _make()
        events: list = []
        ctl._dim_surface = _StubSurface("dim", events)
        ctl._radial_surface = _StubSurface("radial", events)
        ctl._restack_radial_layers()
        raised = [key for (key, method) in events if method == "raise_"]
        assert raised == ["dim", "radial"]   # dim lower, radial on top

    def test_close_radial_menu_tears_down_the_dim(self, qapp):
        ctl, factory, win = _make()
        events: list = []
        radial = _StubSurface("radial", events); dim = _StubSurface("dim", events)
        ctl._radial_surface = radial; ctl._radial_menu = object(); ctl._radial_size = 100
        ctl._dim_surface = dim; ctl._dim_size = 100
        ctl.close_radial_menu()
        assert ctl._radial_surface is None and ctl._dim_surface is None
        assert "hide" in dim.methods() and "deleteLater" in dim.methods()

    def test_is_radial_open_reflects_surface(self, qapp):
        # The emblem-click toggle relies on this to decide open vs close.
        ctl, factory, win = _make()
        assert ctl.is_radial_open is False
        ctl._radial_surface = _StubSurface("radial", [])
        assert ctl.is_radial_open is True
        ctl._radial_surface = None
        assert ctl.is_radial_open is False

    def test_teardown_dim_is_idempotent(self, qapp):
        ctl, factory, win = _make()
        ctl._teardown_dim()                  # nothing open -> no error
        events: list = []
        ctl._dim_surface = _StubSurface("dim", events); ctl._dim_size = 100
        ctl._teardown_dim()
        assert ctl._dim_surface is None and ctl._dim_size == 0
        ctl._teardown_dim()                  # again -> still safe

    def test_teardown_dim_clears_widget_ref(self, qapp):
        ctl, factory, win = _make()
        ctl._dim_surface = _StubSurface("dim", []); ctl._dim_size = 50
        ctl._dim_widget = object()
        ctl._teardown_dim()
        assert ctl._dim_widget is None

    def test_build_dim_creates_clickthrough_dim_and_reveals(self, qapp, monkeypatch):
        ctl, factory, win = _make()
        from PySide6.QtCore import QRect
        calls = []

        class _DimSurf:
            def __init__(self, *a, **k): pass
            def host(self, w): self.w = w
            def set_overlay_geometry(self, g): pass
            def prepare_initial_state(self): pass
            def show(self): calls.append("show")
            def apply_shape(self, path, dpr): calls.append(("apply_shape", path.isEmpty()))
            def devicePixelRatio(self): return 1.0

        class _DimWidget:
            def __init__(self, *a, **k): pass
            def start_reveal(self, animate=True): calls.append("reveal")

        monkeypatch.setattr("utils.overlay.surface.OverlaySurface", _DimSurf)
        monkeypatch.setattr("utils.overlay.radial_menu.RadialDimWidget", _DimWidget)
        ctl._build_dim(QRect(0, 0, 100, 100))
        # No card grab anymore: just show -> empty (click-through) shape -> reveal.
        assert "show" in calls and "reveal" in calls
        assert ("apply_shape", True) in calls           # EMPTY path => click-through
        assert not hasattr(ctl, "_grab_backdrop")       # helper deleted
        assert not hasattr(ctl, "_dim_dpr")             # helper deleted

    def test_collapse_dim_noop_when_no_widget(self, qapp):
        ctl, factory, win = _make()
        ctl._collapse_dim()                  # _dim_widget is None -> must not raise

    def test_collapse_dim_calls_start_close_on_widget(self, qapp):
        ctl, factory, win = _make()
        calls = []
        class _StubDimWidget:
            def start_close(self, animate=True):
                calls.append(animate)
        ctl._dim_widget = _StubDimWidget()
        ctl._collapse_dim()
        assert calls, "start_close was not called"


# ---------------------------------------------------------------------------
# _reposition_radial() — size-aware live re-size on scale change
# ---------------------------------------------------------------------------
class _FakeRadialMenu:
    """Records set_emblem_diameter calls; stands in for RadialMenuWidget."""
    def __init__(self):
        self.diameters = []

    def set_emblem_diameter(self, d):
        self.diameters.append(d)


# ---------------------------------------------------------------------------
# Scale-gesture snapshot seam (Task 4): layer gathering + settle + scale
# ---------------------------------------------------------------------------
class _StubProvider:
    """Minimal card-provider stand-in for the layer-gathering tests.

    The gather tests stub ``_render_layer`` outright, so none of these accessors
    are exercised; the provider only needs to exist so the controller reports as
    provider-backed when those tests want it to."""
    def slot_widget(self, i): return object()
    def emblem_widget(self): return object()
    def capture_slot(self, w): return None
    def restore_slot(self, rec): pass
    def apply_metrics(self, m): pass
    def control_rects(self, slot): return []


class TestGatherScaleLayers:
    def test_gather_layers_zorder_visible_cards(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        ctl._visible_cells = {0, 1, 2, 3}
        # Tag, not a real Layer: isolates the gather Z-ORDER from the live render.
        ctl._render_layer = lambda kind, idx=None: (kind, idx)
        layers = ctl._gather_scale_layers()
        # glow, the four visible cards (0-3, in order), then the emblem LAST.
        assert layers[0] == ("glow", None)
        assert layers[1:5] == [("card", 0), ("card", 1), ("card", 2), ("card", 3)]
        assert layers[-1] == ("emblem", None)
        # Radial closed -> no dim/radial; the settings panel never scales.
        kinds = [k for (k, _i) in layers]
        assert "dim" not in kinds and "radial" not in kinds and "panel" not in kinds

    def test_gather_layers_only_visible_cards(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        ctl._visible_cells = {0, 2}            # partial occupancy
        ctl._render_layer = lambda kind, idx=None: (kind, idx)
        layers = ctl._gather_scale_layers()
        cards = [(k, i) for (k, i) in layers if k == "card"]
        assert cards == [("card", 0), ("card", 2)]   # only 0 and 2, not 1/3

    def test_gather_layers_includes_dim_and_radial_when_open(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        ctl._radial_surface = object()        # truthy -> radial open
        ctl._visible_cells = {0}
        ctl._render_layer = lambda kind, idx=None: (kind, idx)
        layers = ctl._gather_scale_layers()
        kinds = [k for (k, _i) in layers]
        assert "dim" in kinds and "radial" in kinds
        assert kinds.index("dim") < kinds.index("emblem")    # dim below emblem
        assert kinds.index("radial") > kinds.index("emblem")  # radial above emblem


class TestSettleAndScale:
    def test_settle_placement_calls_recompute_now(self, qapp):
        ctl, factory, win = _make()
        calls = []
        ctl._recompute_now = lambda: calls.append(True)
        ctl.settle_placement()
        assert calls == [True]

    def test_scale_property_sets_and_mirrors(self, qapp):
        ctl, factory, win = _make()
        ctl.scale = 1.3
        assert ctl._scale == 1.3
        assert all(st.scale == 1.3 for st in ctl._states)


class TestRepositionRadialResize:
    def test_resizes_radial_and_dim_to_scale_when_open(self, qapp):
        ctl, factory, win = _make()
        ctl._anchor = (600, 600)
        ctl._scale = step_scale(1.0, 3)                 # scaled up from default
        emblem_dia = float(CardMetrics(ctl._scale).emblem)
        expected = int(emblem_dia * 4)
        menu = _FakeRadialMenu()
        ctl._radial_surface = _StubSurface("radial", [])
        ctl._radial_menu = menu
        ctl._radial_size = 1                            # stale -> forces a resize
        ctl._dim_surface = _StubSurface("dim", [])
        ctl._dim_size = 1
        ctl._reposition_radial()
        assert ctl._radial_size == expected
        assert ctl._dim_size == expected
        assert menu.diameters == [emblem_dia]           # re-geometried once
        # The click-region re-apply is DEFERRED to a settle timer (re-applying
        # the X11 input shape on every scroll tick stalls the wheel stream), so
        # nothing is applied inline; a reshape is scheduled instead.
        assert ctl._radial_surface.shapes == []
        assert ctl._radial_reshape_timer is not None
        assert ctl._radial_reshape_timer.isActive()
        # re-centered at the new canvas size
        g = ctl._radial_surface.geometry
        assert g.width() == expected and g.height() == expected

    def test_deferred_reshape_applies_click_region_at_current_size(self, qapp):
        ctl, factory, win = _make()
        ctl._radial_surface = _StubSurface("radial", [])
        ctl._radial_size = 800
        ctl._reapply_radial_shape()                     # what the settle timer fires
        assert len(ctl._radial_surface.shapes) == 1     # applied once, on settle
        path, _dpr = ctl._radial_surface.shapes[0]
        assert path.boundingRect().width() == 800       # full canvas at current size

    def test_deferred_reshape_is_noop_after_close(self, qapp):
        ctl, factory, win = _make()
        ctl._radial_surface = None                      # menu already closed
        ctl._reapply_radial_shape()                     # must not raise

    def test_same_scale_does_not_resize_or_reshape(self, qapp):
        ctl, factory, win = _make()
        ctl._anchor = (600, 600)
        ctl._scale = 1.0
        size = int(float(CardMetrics(1.0).emblem) * 4)
        menu = _FakeRadialMenu()
        ctl._radial_surface = _StubSurface("radial", [])
        ctl._radial_menu = menu
        ctl._radial_size = size                         # already current
        ctl._dim_surface = _StubSurface("dim", [])
        ctl._dim_size = size
        ctl._reposition_radial()
        assert menu.diameters == []                     # no re-geometry
        assert ctl._radial_surface.shapes == []         # no shape re-apply
        assert ctl._radial_size == size and ctl._dim_size == size


class TestLayerRenderingSeam:
    """Direct coverage of the riskiest seam bits (_layer_widget / _render_layer)
    that the gather tests stub out - the real card-viewport selection, screen
    top-left, absent-card None, and that a Layer is produced."""

    def test_layer_widget_and_render_for_a_card(self, qapp):
        from PySide6.QtWidgets import QWidget
        from PySide6.QtCore import QRect, QPoint
        from utils.overlay.surface import CardSurface
        from utils.overlay.scale_snapshot import Layer
        ctl, factory, win = _make()
        cs = CardSurface(0)
        card = QWidget(); card.setFixedSize(100, 80)
        cs.host(card, base_size=(100, 80))
        cs.set_overlay_geometry(QRect(50, 60, 150, 120))
        cs.show(); qapp.processEvents()
        ctl._surfaces = [cs]
        try:
            widget, tl = ctl._layer_widget("card", 0)
            assert widget is cs._scaled_view._view.viewport()  # real card paint device
            assert tl == QPoint(50, 60)                         # surface screen top-left
            layer = ctl._render_layer("card", 0)
            assert isinstance(layer, Layer)
            assert layer.top_left == QPoint(50, 60)
            assert layer.image.width() > 0 and layer.image.height() > 0
        finally:
            cs.release()
            cs.hide()

    def test_layer_widget_none_for_absent_card(self, qapp):
        from PySide6.QtCore import QRect
        from utils.overlay.surface import CardSurface
        ctl, factory, win = _make()
        cs = CardSurface(0)                     # nothing hosted
        cs.set_overlay_geometry(QRect(0, 0, 50, 50))
        ctl._surfaces = [cs]
        try:
            assert ctl._layer_widget("card", 0) == (None, None)
            assert ctl._render_layer("card", 0) is None
        finally:
            cs.hide()


# ---------------------------------------------------------------------------
# Scale-gesture proxy wiring (Task 4): routing, snapshot host, hide/show, settle
# ---------------------------------------------------------------------------
class TestScaleProxyGesture:
    def test_provider_scale_routes_to_proxy(self, qapp):
        """A provider-backed scale notch routes through the snapshot-proxy gesture
        coordinator, NOT the old synchronous _schedule_recompute path."""
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        begun = []
        recomputes = []
        ctl._begin_or_continue_scale = lambda n: begun.append(n)
        ctl._schedule_recompute = lambda: recomputes.append(True)
        ctl.set_scale_by_notches(2)
        assert begun == [2]              # routed to the gesture coordinator
        assert recomputes == []          # the coordinator owns the ramp, not this

    def test_no_provider_scale_stays_synchronous(self, qapp):
        """With no card_provider the placeholder path still steps the scale
        synchronously (the Task 3.2 stub-orchestration contract)."""
        ctl, factory, win = _make()
        ctl.enter()
        before = ctl._scale
        ctl.set_scale_by_notches(1)
        assert ctl._scale == step_scale(before, 1)

    def test_snapshot_returns_5tuple(self, qapp):
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QImage
        from utils.overlay.scale_snapshot import Layer
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        ctl._visible_cells = {0, 1, 2, 3}
        # Real surfaces expose geometry() as a method; adapt the stub emblem so
        # snapshot() can read its screen rect + dpr.
        emblem = ctl._surfaces[-1]
        geo = emblem.geometry
        emblem.geometry = lambda: geo

        def _layers():
            img1 = QImage(10, 8, QImage.Format_ARGB32_Premultiplied); img1.fill(0)
            img2 = QImage(12, 6, QImage.Format_ARGB32_Premultiplied); img2.fill(0)
            return [Layer(img1, QPoint(100, 100)), Layer(img2, QPoint(140, 120))]

        ctl._gather_scale_layers = _layers
        result = ctl.snapshot()
        assert len(result) == 5
        snap, bbox, anchor, wheel, dpr = result
        assert isinstance(snap, QImage) and not snap.isNull()
        assert isinstance(bbox, QRect)
        assert isinstance(anchor, QPoint)
        assert isinstance(wheel, list)
        assert isinstance(dpr, float)

    def test_hide_show_skip_panel_and_use_visible_cards(self, qapp):
        ctl, factory, win = _make()
        ctl.enter()
        ctl._card_provider = _StubProvider()
        ctl._visible_cells = {0, 2}
        panel = _StubSurface("panel", [])
        ctl._panel_surface = panel
        cards = factory.created           # [card0, card1, card2, card3, emblem]
        for s in cards:
            s.calls.clear()
        ctl.hide_scaling_windows()
        assert "hide" in cards[0].methods()       # card 0 visible -> hidden
        assert "hide" in cards[2].methods()       # card 2 visible -> hidden
        assert "hide" not in cards[1].methods()   # card 1 empty -> untouched
        assert "hide" not in cards[3].methods()   # card 3 empty -> untouched
        assert "hide" in cards[-1].methods()      # emblem always a scaling surface
        assert "hide" not in panel.methods()      # the settings panel never scales
        # And show brings the same set back (panel still untouched).
        for s in cards:
            s.calls.clear()
        ctl.show_scaling_windows()
        assert "show" in cards[0].methods() and "show" in cards[2].methods()
        assert "show" not in cards[1].methods() and "show" not in cards[3].methods()
        assert "show" in cards[-1].methods()
        assert "show" not in panel.methods()

    def test_on_gesture_end_applies_deferred_occupancy(self, qapp):
        ctl, factory, win = _make()
        ctl._occupancy_deferred = True
        calls = []
        ctl._reconcile_visibility = lambda: calls.append(True)
        ctl.on_gesture_end()
        assert calls == [True]
        assert ctl._occupancy_deferred is False

    def test_on_gesture_end_skips_reconcile_when_not_deferred(self, qapp):
        ctl, factory, win = _make()
        ctl._occupancy_deferred = False
        calls = []
        ctl._reconcile_visibility = lambda: calls.append(True)
        ctl.on_gesture_end()
        assert calls == []
        assert ctl._occupancy_deferred is False
