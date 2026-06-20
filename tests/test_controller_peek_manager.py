# tests/test_controller_peek_manager.py
import pytest
from PySide6.QtCore import QRect
from utils.overlay.group_controller import OverlayGroupController, SurfaceState


class _RecordingProvider:
    """Records the extra-tier opacities pushed per shell by the controller fade."""
    def __init__(self):
        self.calls = []  # (surface_id, bg_extra, portrait_extra)

    def set_shell_extra_opacity(self, surface_id, bg_opacity, portrait_opacity):
        self.calls.append((surface_id, round(float(bg_opacity), 4),
                           round(float(portrait_opacity), 4)))

    def control_rects(self, slot):
        return []


class _PeekStubSurface:
    def __init__(self, state, geom):
        self.state = state
        self._geom = geom
        self.peeks = []          # history of set_peek(active) calls
        self.content = []        # history of set_content_opacity() values

    def geometry(self): return self._geom
    def set_peek(self, active, control_rects=None):
        self.peeks.append(bool(active))
    def set_content_opacity(self, opacity):
        self.content.append(round(float(opacity), 4))


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


def _card_surfaces(c):
    return [s for s, st in zip(c._surfaces, c._states) if not st.is_emblem]


def test_peek_fade_reaches_two_tiers_then_restores(qapp):
    c = OverlayGroupController(window=None, surface_factory=lambda s: None,
                              card_provider=_RecordingProvider())
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    prov = c._card_provider
    su0 = _card_surfaces(c)[0]
    for _ in range(10):           # hover card 0 -> full peek
        c._peek_tick((50, 50))
    assert c._peek_progress[0] == pytest.approx(1.0, abs=1e-6)
    assert c._peek_progress[1] == 0.0
    # Content tier: whole card to 0.80.
    assert su0.content[-1] == pytest.approx(0.80, abs=1e-6)
    assert su0.content == sorted(su0.content, reverse=True)   # monotonic fade-down
    # Extra tiers: net body = content*bg == 0.65; net portrait = content*portrait == 0.50.
    last = [c for c in prov.calls if c[0] == 0][-1]
    _, bg0, portrait0 = last
    assert su0.content[-1] * bg0 == pytest.approx(0.65, abs=1e-6)
    assert su0.content[-1] * portrait0 == pytest.approx(0.50, abs=1e-6)
    assert all(c[0] == 0 for c in prov.calls)  # idle cards never repaint
    for _ in range(10):           # move off -> back to opaque
        c._peek_tick((500, 500))
    assert c._peek_progress[0] == pytest.approx(0.0, abs=1e-6)
    assert su0.content[-1] == pytest.approx(1.0, abs=1e-6)


def test_stop_peek_timer_restores_opacity(qapp):
    c = OverlayGroupController(window=None, surface_factory=lambda s: None,
                              card_provider=_RecordingProvider())
    geoms = {0: QRect(0, 0, 100, 100), 1: QRect(200, 0, 100, 100),
             2: QRect(0, 200, 100, 100), 3: QRect(200, 200, 100, 100)}
    _wire(c, geoms)
    su0 = _card_surfaces(c)[0]
    for _ in range(10):
        c._peek_tick((50, 50))
    assert c._peek_progress[0] == pytest.approx(1.0)
    c._stop_peek_timer()
    assert c._peek_progress == [0.0, 0.0, 0.0, 0.0]
    assert su0.content[-1] == pytest.approx(1.0)
    assert c._card_provider.calls[-1] == (0, 1.0, 1.0)
