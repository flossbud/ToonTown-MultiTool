# tests/test_controller_controls_region.py
from PySide6.QtCore import QRect
from utils.overlay.group_controller import OverlayGroupController, SurfaceState


class _StubSurface:
    def __init__(self, state):
        self.state = state
        self.region_calls = []
        self.shape_calls = []
        self._geom = QRect(0, 0, 100, 100)

    # geometry / lifecycle no-ops used by enter()/place
    def set_overlay_geometry(self, rect): self._geom = rect
    def geometry(self): return self._geom
    def devicePixelRatio(self): return 1.0
    def prepare_initial_state(self): pass
    def show(self): pass
    def raise_(self): pass
    def lower(self): pass
    def set_card_scale(self, s): pass
    def host(self, *a, **k): pass
    def release(self): return None
    def windowHandle(self): return None

    def apply_input_region(self, region):
        self.region_calls.append(region)

    def apply_shape(self, path, dpr):
        self.shape_calls.append((path, dpr))


class _StubProvider:
    def slot_widget(self, i): return object()
    def emblem_widget(self): return object()
    def capture_slot(self, w): return None
    def restore_slot(self, rec): pass
    def apply_metrics(self, m): pass
    def control_rects(self, slot):
        # one 10x10 control near the card origin
        return [QRect(2, 2, 10, 10)]


def _controller():
    surfaces = {}

    def factory(state):
        s = _StubSurface(state)
        surfaces[id(state)] = s
        return s

    c = OverlayGroupController(window=None, surface_factory=factory,
                              card_provider=_StubProvider())
    return c, surfaces


def test_cards_get_controls_region_emblem_gets_disc_path(qapp):
    c, _ = _controller()
    state_card = SurfaceState(surface_id=0)
    state_emblem = SurfaceState(surface_id=-1, is_emblem=True)
    card_surface = _StubSurface(state_card)
    emblem_surface = _StubSurface(state_emblem)

    c._apply_input_region(state_card, card_surface, QRect(0, 0, 100, 100))
    c._apply_input_region(state_emblem, emblem_surface, QRect(0, 0, 80, 80))

    assert len(card_surface.region_calls) == 1
    assert card_surface.shape_calls == []          # card no longer uses body path
    assert len(emblem_surface.shape_calls) == 1    # emblem still a disc path
    assert emblem_surface.region_calls == []


def test_card_without_provider_rects_falls_back_to_body_path(qapp):
    c, _ = _controller()
    c._card_provider = None                          # no provider -> legacy body path
    state_card = SurfaceState(surface_id=0)
    card_surface = _StubSurface(state_card)
    c._apply_input_region(state_card, card_surface, QRect(0, 0, 100, 100))
    assert len(card_surface.shape_calls) == 1
    assert card_surface.region_calls == []
