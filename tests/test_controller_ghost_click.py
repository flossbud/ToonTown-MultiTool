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
    controller._visible_cells = {0, 1}
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


def test_uses_surface_id_not_list_index(qapp):
    # Permuted cluster: list index != surface_id, so a regression using the
    # enumerate index instead of st.surface_id would deliver the WRONG id. This
    # guards the documented 2-toon permuted-cluster bug class.
    c, provider = _make((True, True))
    c._states = [SurfaceState(surface_id=2), SurfaceState(surface_id=0)]
    c._surfaces = [
        _StubSurface(c._states[0], QRect(100, 100, 200, 200)),  # index 0, id 2
        _StubSurface(c._states[1], QRect(400, 100, 200, 200)),  # index 1, id 0
    ]
    c._visible_cells = {2, 0}  # both surfaces are mapped for this permutation test
    c.on_ghost_event(("press", [(0, 115, 115)]))   # in the index-0 surface (id 2)
    c.on_ghost_event(("press", [(0, 415, 115)]))   # in the index-1 surface (id 0)
    assert provider.delivered == [(2, 15, 15), (0, 15, 15)]


def test_gate_off_when_inactive(qapp):
    c, provider = _make((True, True))
    c._active = False
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == []


def test_gate_off_when_no_provider(qapp):
    c, provider = _make((True, True))
    c._card_provider = None
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == []


def test_gate_off_when_no_settings(qapp):
    provider = _RecordingProvider()
    c = OverlayGroupController(window=None, settings=None, card_provider=provider)
    _wire(c, provider)
    c.on_ghost_event(("press", [(0, 115, 115)]))
    assert provider.delivered == []


def test_ghost_click_skips_hidden_card(qapp):
    c, provider = _make((True, True))
    c._visible_cells = {0}                  # card 1 hidden (no window there)
    # (420,120) is on card 1's control (card-local (20,20)), but card 1 is hidden:
    c._ghost_click_pass([(0, 420, 120)])
    assert provider.delivered == []
    # (120,120) is on visible card 0's control -> delivers to surface_id 0:
    c._ghost_click_pass([(0, 120, 120)])
    assert provider.delivered and provider.delivered[-1][0] == 0
