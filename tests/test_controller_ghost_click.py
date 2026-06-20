# tests/test_controller_ghost_click.py
from PySide6.QtCore import QRect
from utils.overlay.group_controller import OverlayGroupController, SurfaceState


class _StubSurface:
    def __init__(self, state, geom):
        self.state = state
        self._geom = geom

    def geometry(self):
        return self._geom

    def set_peek(self, active):
        pass

    def set_content_opacity(self, o):
        pass


class _RecordingProvider:
    def __init__(self):
        self.delivered = []

    def control_rects(self, surface_id):
        # one control at card-local (10,10,40,40)
        return [QRect(10, 10, 40, 40)]

    def set_shell_extra_opacity(self, *a, **k):
        pass

    def deliver_ghost_click(self, cell_index, x, y):
        self.delivered.append((cell_index, x, y))


class _Settings:
    def __init__(self, vals):
        self._vals = vals

    def get(self, key, default=None):
        return self._vals.get(key, default)


def _wire(controller, provider):
    # Two card surfaces at known global geometry; scale 1.0.
    s0 = SurfaceState(surface_id=0)
    s1 = SurfaceState(surface_id=1)
    controller._states = [s0, s1]
    controller._surfaces = [
        _StubSurface(s0, QRect(100, 100, 200, 200)),
        _StubSurface(s1, QRect(400, 100, 200, 200)),
    ]
    controller._card_provider = provider
    controller._active = True
    controller._scale = 1.0


def _make(vals):
    from utils.settings_keys import (
        GHOST_CURSORS_ENABLED, GHOST_CURSORS_CONTROL_CARDS)
    provider = _RecordingProvider()
    c = OverlayGroupController(
        window=None,
        settings=_Settings({GHOST_CURSORS_ENABLED: vals[0],
                            GHOST_CURSORS_CONTROL_CARDS: vals[1]}),
        card_provider=provider)
    _wire(c, provider)
    return c, provider


def test_press_on_control_delivers_click(qapp):
    c, provider = _make((True, True))
    # global (115,115) in surface 0 -> local (15,15), inside (10,10,40,40).
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == [(0, 15, 15)]


def test_press_on_body_delivers_nothing(qapp):
    c, provider = _make((True, True))
    # local (90,90): in the card, not on the control.
    c.on_ghost_event(("press", [(0, 190, 190)]))
    assert provider.delivered == []


def test_motion_and_release_never_click(qapp):
    c, provider = _make((True, True))
    c.on_ghost_event(("motion", [(0, 115, 115)]))
    c.on_ghost_event(("release", [(0, 115, 115)]))
    assert provider.delivered == []


def test_gate_off_when_control_setting_off(qapp):
    c, provider = _make((True, False))
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == []


def test_gate_off_when_ghosts_off(qapp):
    c, provider = _make((False, True))
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == []


def test_uses_surface_id_for_second_card(qapp):
    c, provider = _make((True, True))
    # global (415,115) in surface 1 -> local (15,15), inside the control.
    c.on_ghost_event(("press", [(1, 415, 115)]))
    assert provider.delivered == [(1, 15, 15)]
