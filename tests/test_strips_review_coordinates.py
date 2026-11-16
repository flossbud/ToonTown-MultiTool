"""Native rectangles use a single display's scale, including their far edge."""
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QRegion
from utils.strips.attach import AttachStrategy, Win32TopmostAttach
from utils.strips.strip_surface import StripSurface
from tests.test_strips_controller import Backend


class Screen:
    def __init__(self, geometry, ratio):
        self._geometry, self._ratio = geometry, ratio
    def geometry(self):
        return self._geometry
    def devicePixelRatio(self):
        return self._ratio


def desktop(monkeypatch):
    screens = [Screen(QRect(0, 0, 1280, 720), 1.5),
               Screen(QRect(1920, 0, 1920, 1080), 1)]
    monkeypatch.setattr(QGuiApplication, 'screens', lambda: screens)


def test_client_far_corner_on_adjacent_monitor_does_not_change_scale(qapp, monkeypatch):
    desktop(monkeypatch)
    surface = StripSurface(AttachStrategy(), Backend(), 1)
    surface._client = (0, 0, 1920, 900)
    assert surface.client_logical() == QRect(0, 0, 1280, 600)
    surface.deleteLater()


def test_win32_gate_uses_the_same_rect_scale_as_placement(qapp, monkeypatch):
    desktop(monkeypatch)
    from utils import ghost_cursors
    monkeypatch.setattr(ghost_cursors, '_win32_zorder_snapshot',
                        lambda: [(123, (0, 0, 1920, 900), 1)])
    monkeypatch.setattr('utils.strips.attach._win32_frame_bounds', lambda _: None)
    # This logical strip is beyond the actual right edge of the game.
    assert Win32TopmostAttach().visible_region(QRect(1400, 20, 200, 40), '123', []).isEmpty()
