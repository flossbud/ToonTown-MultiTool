"""Popover gates are applied before first presentation, not on the next sweep."""
import pytest
from PySide6.QtGui import QRegion
from tests.test_strips_controller import rig, settle


@pytest.mark.parametrize('kind', ['home', 'counters'])
def test_covered_popup_is_never_presented_before_first_sweep(rig, kind):
    session, controller, _ = rig()
    strategy = controller.follower.strategy
    strategy.gated = True
    strategy.visible_region = lambda *_a, **_k: QRegion()
    if kind == 'home':
        controller.toggle_home_panel('101')
        surface = controller.popovers.open_surface('101')
    else:
        session.set_counters_locked('102', True)
        surface = controller.popovers.counters_surface('102')
    settle()
    assert surface is not None
    assert not surface.is_presented()
    assert surface.windowOpacity() == 0
    # Lifting the covering window restores the already-attached popup.
    strategy.visible_region = lambda *_a, **_k: None
    controller.popovers._sweep(strategy, controller.follower.own_window_ids())
    assert surface.is_presented()
