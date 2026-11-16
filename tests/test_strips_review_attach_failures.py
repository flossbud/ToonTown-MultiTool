"""An attachment failure must leave both kinds of overlay inert."""
import pytest
from PySide6.QtCore import QPoint
from utils.strips.popovers.home import HomePanel
from utils.strips.popovers.surface import PopoverSurface
from utils.strips.strip_surface import StripSurface
from tests.test_strips_controller import Backend, Strategy, settle


class Fallible(Strategy):
    result = True

    def attach(self, *_):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize('result', [False, OSError('server unavailable')])
def test_popup_failed_first_attachment_never_presents(qapp, result):
    strategy, backend = Fallible(), Backend()
    strategy.result = result
    surface = PopoverSurface(strategy, backend, HomePanel())
    surface.present(QPoint(100, 100), 123)
    settle()
    assert not surface.is_presented()
    assert surface.windowOpacity() == 0
    assert backend.last.isEmpty()
    surface.dismiss()


@pytest.mark.parametrize('kind', ['strip', 'popover'])
def test_failed_reattachment_clears_old_success_and_input(qapp, kind):
    strategy, backend = Fallible(), Backend()
    if kind == 'strip':
        surface = StripSurface(strategy, backend, 1)
        surface.set_game_window('123')
        surface.place((0, 0, 800, 600))
    else:
        surface = PopoverSurface(strategy, backend, HomePanel())
        surface.present(QPoint(100, 100), 123)
    settle()
    assert surface.is_presented()
    strategy.result = False
    if kind == 'strip':
        surface._reassert()
    else:
        surface._restack()
    assert not surface.is_presented()
    assert backend.last.isEmpty()
    surface.close()
    surface.deleteLater()
