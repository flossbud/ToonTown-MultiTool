"""Opacity staging must also stage the native input region."""
import pytest
from PySide6.QtCore import QPoint
from utils.strips.popovers.home import HomePanel
from utils.strips.popovers.surface import PopoverSurface
from utils.strips.strip_surface import StripSurface
from tests.test_strips_controller import Backend, Strategy, settle


@pytest.mark.parametrize('kind', ['strip', 'popover'])
def test_first_map_already_has_empty_input_before_first_paint(qapp, kind):
    backend = Backend()
    seen = []
    base = StripSurface if kind == 'strip' else PopoverSurface

    class Surface(base):
        def showEvent(self, event):
            region = getattr(backend, 'last', None)
            seen.append(region is not None and region.isEmpty())
            super().showEvent(event)

    if kind == 'strip':
        surface = Surface(Strategy(), backend, 1)
        surface.set_game_window('123')
        surface.place((0, 0, 800, 600))
    else:
        surface = Surface(Strategy(), backend, HomePanel())
        surface.present(QPoint(100, 100), 123)
    assert seen == [True]
    assert backend.last.isEmpty()
    settle()
    assert surface.is_presented()
    assert not backend.last.isEmpty()
    surface.close()
    surface.deleteLater()
