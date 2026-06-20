# tests/test_controller_peek_manager.py
from PySide6.QtCore import QRect
from utils.overlay.group_controller import OverlayGroupController, SurfaceState


class _PeekStubSurface:
    def __init__(self, state, geom):
        self.state = state
        self._geom = geom
        self.peeks = []          # history of set_peek(active) calls

    def geometry(self): return self._geom
    def set_peek(self, active, control_rects=None):
        self.peeks.append(bool(active))


def _wire(c, geoms):
    """Attach stub card surfaces (and a stub emblem) at the given geometries."""
    c._surfaces = []
    for st in c._states:
        if st.is_emblem:
            c._surfaces.append(_PeekStubSurface(st, QRect(0, 0, 1, 1)))
        else:
            c._surfaces.append(_PeekStubSurface(st, geoms[st.surface_id]))
    c._active = True


def _controller():
    return OverlayGroupController(window=None, surface_factory=lambda s: None,
                                 card_provider=None)


def test_real_cursor_over_one_card_peeks_only_that_card(qapp):
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c._peek_tick((50, 50))      # over card 0
    cards = [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]
    assert cards[0].peeks[-1] is True
    assert cards[1].peeks[-1] is False
    assert cards[2].peeks[-1] is False
    assert cards[3].peeks[-1] is False


def test_ghost_points_drive_peek_without_real_cursor(qapp):
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c.on_ghost_event(("motion", [(1, 250, 50)]))   # ghost over card 1
    c._peek_tick(None)                              # no real cursor
    cards = [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]
    assert cards[1].peeks[-1] is True
    assert cards[0].peeks[-1] is False


def test_ghost_clear_stops_peek(qapp):
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c.on_ghost_event(("motion", [(1, 250, 50)]))
    c._peek_tick(None)
    c.on_ghost_clear()
    c._peek_tick(None)
    cards = [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]
    assert cards[1].peeks[-1] is False


def test_peek_tick_noop_when_inactive(qapp):
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c._active = False
    c._peek_tick((50, 50))
    cards = [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]
    assert cards[0].peeks == []     # nothing applied while inactive


def test_real_cursor_and_ghost_peek_different_cards_together(qapp):
    # The core union: real pointer over card 0 AND a ghost over card 2 -> both
    # peek, the other two do not (the broadcasting case).
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c.on_ghost_event(("motion", [(2, 50, 250)]))   # ghost over card 2
    c._peek_tick((50, 50))                          # real cursor over card 0
    cards = [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]
    assert cards[0].peeks[-1] is True
    assert cards[2].peeks[-1] is True
    assert cards[1].peeks[-1] is False
    assert cards[3].peeks[-1] is False


def test_stop_peek_timer_clears_ghost_store(qapp):
    # Ghost positions must not survive a leave()/enter() cycle.
    c = _controller()
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    c.on_ghost_event(("motion", [(1, 250, 50)]))
    assert c._peek_store.points() != []
    c._stop_peek_timer()
    assert c._peek_store.points() == []
