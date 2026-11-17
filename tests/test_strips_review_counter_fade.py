"""Counter opacity transitions preserve stacking, input and concealment gates."""
import pytest
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QRegion
from tests.test_strips_controller import Backend, Keymaps, Strategy, rig, settle
from utils import motion
from utils.strips import layout as L
from utils.strips.popovers.counters import CountersView
from utils.strips.popovers.surface import PopoverSurface


@pytest.fixture
def make(qapp, monkeypatch):
    monkeypatch.setattr(motion, 'is_reduced', lambda: False)
    monkeypatch.setattr(motion, '_TEST_DURATION_SCALE', 1.0)
    made = []
    def build(strategy=None):
        backend = Backend()
        surface = PopoverSurface(strategy or Strategy(), backend, CountersView(), fade=True)
        made.append(surface)
        return surface, backend
    yield build
    for surface in made:
        surface.dismiss()


def show(surface):
    surface.present(QPoint(100, 100), 123)
    settle()


def finish(surface):
    surface._fade.setCurrentTime(surface._fade.duration())


def test_fade_starts_after_first_paint_attach_and_input_waits_until_fully_in(make):
    surface, backend = make()
    surface.present(QPoint(100, 100), 123)
    assert not surface._attached
    assert surface.windowOpacity() == 0
    assert backend.last.isEmpty()
    assert surface._fade.state() == QAbstractAnimation.Stopped
    settle()
    assert surface._attached
    assert surface._fade.state() == QAbstractAnimation.Running
    assert surface._fade.duration() == 140
    assert surface._fade.easingCurve().type() == QEasingCurve.OutCubic
    surface._fade.setCurrentTime(70)
    assert 0 < surface.windowOpacity() < 1
    assert backend.last.isEmpty() and not surface.is_presented()
    finish(surface)
    assert surface.windowOpacity() == 1
    assert not backend.last.isEmpty() and surface.is_presented()


def test_fade_out_drops_input_at_start_and_reaches_zero_in_100ms(make):
    surface, backend = make()
    show(surface)
    finish(surface)
    surface.conceal()
    assert surface.windowOpacity() == 1
    assert backend.last.isEmpty() and not surface.is_presented()
    assert surface._fade.duration() == 100
    surface._fade.setCurrentTime(50)
    assert 0 < surface.windowOpacity() < 1
    finish(surface)
    assert surface.windowOpacity() == 0
    assert backend.last.isEmpty()


def test_show_during_fade_out_reverses_from_current_opacity(make):
    surface, backend = make()
    show(surface)
    finish(surface)
    surface.conceal()
    surface._fade.setCurrentTime(40)
    current = surface.windowOpacity()
    writes = []
    set_opacity = surface.setWindowOpacity
    surface.setWindowOpacity = lambda value: (writes.append(value), set_opacity(value))[-1]
    surface.present(surface.pos(), 123)
    assert surface._fade.startValue() == pytest.approx(current, abs=1/255)
    assert surface.windowOpacity() == pytest.approx(current, abs=1/255)
    assert surface._fade.endValue() == 1
    assert all(abs(value - current) <= 1/255 for value in writes)
    assert backend.last.isEmpty()
    finish(surface)
    assert surface.is_presented()


def test_repositioning_visible_locked_counters_does_not_restart_fade(make):
    surface, _ = make()
    show(surface)
    finish(surface)
    surface.present(QPoint(200, 180), 123)
    assert surface._fade.state() == QAbstractAnimation.Stopped
    assert surface.windowOpacity() == 1 and surface.is_presented()


def test_reposition_during_fade_in_keeps_its_progress(make):
    surface, _ = make()
    show(surface)
    surface._fade.setCurrentTime(70)
    surface.present(QPoint(200, 180), 123)
    assert surface._fade.currentTime() == 70
    assert surface._fade.duration() == 140


@pytest.mark.parametrize('bypass', ['reduce_motion', 'shaped'])
def test_reduced_motion_and_no_compositor_are_instant(make, monkeypatch, bypass):
    strategy = Strategy()
    if bypass == 'reduce_motion':
        monkeypatch.setattr(motion, 'is_reduced', lambda: True)
    else:
        strategy.shaped = lambda: True
    surface, backend = make(strategy)
    show(surface)
    assert surface.windowOpacity() == 1 and surface.is_presented()
    assert surface._fade.state() == QAbstractAnimation.Stopped
    assert not backend.last.isEmpty()
    surface.conceal()
    assert surface.windowOpacity() == 0 and backend.last.isEmpty()


def test_attach_failure_and_coverage_never_start_a_fade(make):
    strategy = Strategy()
    strategy.attach = lambda *_: False
    surface, backend = make(strategy)
    show(surface)
    assert surface.windowOpacity() == 0 and backend.last.isEmpty()
    assert surface._fade.state() == QAbstractAnimation.Stopped
    strategy.attach = lambda *_: True
    surface.set_visible_region(QRegion())
    surface._after_map()
    assert surface.windowOpacity() == 0
    assert surface._fade.state() == QAbstractAnimation.Stopped
    surface.set_visible_region(None)
    assert surface._fade.state() == QAbstractAnimation.Running


def test_immediate_conceal_stops_any_fade_and_show_at_new_place_fades_in(make):
    surface, backend = make()
    show(surface)
    surface._fade.setCurrentTime(70)
    surface.conceal(immediate=True)
    assert surface.windowOpacity() == 0 and backend.last.isEmpty()
    assert surface._fade.state() == QAbstractAnimation.Stopped
    surface.present(QPoint(200, 180), 123)
    assert surface._fade.state() == QAbstractAnimation.Running
    assert surface._fade.startValue() == 0


def test_dismiss_during_fade_stops_animation_and_drops_input(make):
    surface, backend = make()
    show(surface)
    surface._fade.setCurrentTime(60)
    surface.dismiss()
    assert surface._fade.state() == QAbstractAnimation.Stopped
    assert not surface.isVisible() and backend.last.isEmpty()


def test_enabling_reduce_motion_during_fade_finishes_it_immediately(make, monkeypatch):
    surface, backend = make()
    show(surface)
    monkeypatch.setattr(motion, 'is_reduced', lambda: True)
    surface._fade.setCurrentTime(50)
    assert surface._fade.state() == QAbstractAnimation.Stopped
    assert surface.windowOpacity() == 1 and not backend.last.isEmpty()


@pytest.mark.parametrize('cause', ['moving', 'user_hidden'])
def test_controller_hides_counters_immediately_and_fades_them_back(rig, monkeypatch, cause):
    monkeypatch.setattr(motion, 'is_reduced', lambda: False)
    monkeypatch.setattr(motion, '_TEST_DURATION_SCALE', 1.0)
    _, controller, _ = rig()
    pill = controller.popovers.counters_surface('101')
    finish(pill)
    if cause == 'moving':
        controller.follower.surface('101').conceal()
    else:
        controller.set_user_hidden(True)
    assert pill.windowOpacity() == 0 and not pill.is_presented()
    assert pill._fade.state() == QAbstractAnimation.Stopped
    if cause == 'moving':
        controller.follower.surface('101').place((150, 60, 800, 600))
    else:
        controller.set_user_hidden(False)
    assert pill._fade.state() == QAbstractAnimation.Running
    assert pill._fade.startValue() == 0


def test_menus_editor_and_home_keep_instant_presentation(rig, monkeypatch):
    monkeypatch.setattr(motion, 'is_reduced', lambda: False)
    monkeypatch.setattr(motion, '_TEST_DURATION_SCALE', 1.0)
    _, controller, _ = rig(keymaps=Keymaps())
    for open_it in (lambda: controller._on_context('101', L.KEYSET, 1),
                    lambda: controller.open_editor('101', 1),
                    lambda: controller.toggle_home_panel('101')):
        open_it()
        settle()
        surface = controller.popovers.open_surface('101')
        assert not surface._fade_enabled
        assert surface.windowOpacity() == 1 and surface.is_presented()
        controller.popovers.close('101')


def test_bank_update_repositions_locked_pill_without_refading(rig, monkeypatch):
    monkeypatch.setattr(motion, 'is_reduced', lambda: False)
    monkeypatch.setattr(motion, '_TEST_DURATION_SCALE', 1.0)
    session, controller, _ = rig()
    pill = controller.popovers.counters_surface('101')
    finish(pill)
    before = pill.pos()
    session.update_toon('101', bank=999999999)
    assert pill.pos() != before
    assert pill.windowOpacity() == 1 and pill.is_presented()
    assert pill._fade.state() == QAbstractAnimation.Stopped
