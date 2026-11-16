"""Mirrored input honors the same occlusion mask as native input."""
import pytest
from PySide6.QtGui import QRegion
from tests.test_strips_controller import rig
from utils.strips import layout as L


@pytest.mark.parametrize('target', ['enable', 'counter_lock'])
def test_mirrored_press_cannot_toggle_a_control_in_the_covered_region(rig, target):
    session, controller, _ = rig()
    if target == 'enable':
        surface = controller.follower.surface('101')
        block = surface.strip.block_rect(L.ENABLE).toAlignedRect()
        field = 'enabled'
    else:
        surface = controller.popovers.counters_surface('101')
        block = surface.content.lock_rect().toAlignedRect()
        field = 'counters_locked'
    surface.set_visible_region(QRegion(surface.rect()) - QRegion(block))
    assert surface.is_presented()  # only part of the strip is covered
    point = surface.mapToGlobal(block.center())
    assert not controller.ghost_clicks.press(0, point)
    assert getattr(session.toon('101'), field) is True
    surface.set_visible_region(None)
    assert controller.ghost_clicks.press(0, point)
    assert getattr(session.toon('101'), field) is False
