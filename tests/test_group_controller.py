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

    def test_grab_backdrop_none_when_no_screen(self, qapp, monkeypatch):
        ctl, factory, win = _make()
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QRect
        monkeypatch.setattr(QGuiApplication, "screenAt",
                            staticmethod(lambda *a, **k: None))
        monkeypatch.setattr(QGuiApplication, "primaryScreen",
                            staticmethod(lambda *a, **k: None))
        assert ctl._grab_backdrop(QRect(0, 0, 100, 100)) is None
