"""Visibility reconcile for OverlayGroupController: only cells with a detected
window are mapped; the emblem always stays.

Run:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_controller_visibility.py -q
"""
from PySide6.QtCore import QObject, QRect, Signal

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.group_controller import OverlayGroupController, SurfaceState


class _VisSurface:
    def __init__(self, key):
        self.key = key
        self.shown = (key == "emblem")  # emblem starts shown; cards set per test
        self._geom = QRect(0, 0, 10, 10)
        self.calls = []

    def set_overlay_geometry(self, rect):
        self._geom = rect; self.calls.append("geom")

    def geometry(self):
        return self._geom

    def prepare_initial_state(self): self.calls.append("prepare")
    def show(self): self.shown = True; self.calls.append("show")
    def hide(self): self.shown = False; self.calls.append("hide")
    def apply_input_region(self, region): self.calls.append("input_region")
    def apply_shape(self, path, dpr): self.calls.append("shape")
    def raise_(self): self.calls.append("raise")
    def set_peek(self, active): pass
    def set_content_opacity(self, o): pass
    def devicePixelRatio(self): return 1.0


class _VisProvider(QObject):
    occupied_cells_changed = Signal()

    def __init__(self, occupied):
        super().__init__()
        self._occupied = set(occupied)

    def set_occupied(self, occupied):
        self._occupied = set(occupied)
        self.occupied_cells_changed.emit()

    def occupied_cells(self): return frozenset(self._occupied)
    def overlay_base_card_size(self): return (300, 200)
    def emblem_size(self): return 80
    def control_rects(self, c): return [QRect(10, 10, 40, 40)]
    def card_accents(self):
        from PySide6.QtGui import QColor
        return [QColor("#555555")] * 4
    def set_shell_extra_opacity(self, *a): pass


def _make(occupied, visible):
    provider = _VisProvider(occupied)
    c = OverlayGroupController(
        window=None, backend=NoOpOverlayBackend(), card_provider=provider)
    states = [SurfaceState(surface_id=i) for i in range(4)]
    states.append(SurfaceState(surface_id=-1, is_emblem=True))
    c._states = states
    c._surfaces = [_VisSurface(i) for i in range(4)] + [_VisSurface("emblem")]
    for i in range(4):
        c._surfaces[i].shown = i in visible
    c._active = True
    c._scale = 1.0
    c._visible_cells = set(visible)
    c._refresh_glow = lambda rects: None   # glow tested in Task 5
    return c, provider


def _card(c, i): return c._surfaces[i]


def test_reconcile_hides_unoccupied_shows_occupied(qapp):
    c, provider = _make(occupied={0, 2}, visible={0, 1, 2, 3})
    c._reconcile_visibility()
    assert c._visible_cells == {0, 2}
    assert _card(c, 1).shown is False and _card(c, 3).shown is False
    assert _card(c, 0).shown is True and _card(c, 2).shown is True


def test_reconcile_shows_newly_occupied_with_full_transition(qapp):
    c, provider = _make(occupied={0}, visible={0})
    provider.set_occupied({0, 3})
    c._reconcile_visibility()
    assert c._visible_cells == {0, 3}
    calls = _card(c, 3).calls
    assert calls.index("geom") < calls.index("show") < calls.index("input_region")


def test_reconcile_emblem_always_mapped(qapp):
    c, provider = _make(occupied=set(), visible={0, 1, 2, 3})
    c._reconcile_visibility()
    assert c._visible_cells == set()
    assert c._surfaces[-1].shown is True  # emblem untouched


def test_reconcile_noop_when_inactive(qapp):
    c, provider = _make(occupied={0}, visible={0, 1, 2, 3})
    c._active = False
    c._reconcile_visibility()
    assert c._visible_cells == {0, 1, 2, 3}  # unchanged


def test_occupancy_signal_schedules_coalesced_reconcile(qapp):
    c, provider = _make(occupied={0, 1, 2, 3}, visible={0, 1, 2, 3})
    provider.set_occupied({1})          # fires occupied_cells_changed
    qapp.processEvents()                # let the singleShot(0) reconcile run
    assert c._visible_cells == {1}


def test_rapid_signals_coalesce_to_one_final_reconcile(qapp):
    # Three nudges before the event-loop tick must collapse into ONE reconcile
    # that reflects the FINAL occupancy (the core coalescing guarantee).
    c, provider = _make(occupied={0, 1, 2, 3}, visible={0, 1, 2, 3})
    runs = []
    orig = c._reconcile_visibility
    c._reconcile_visibility = lambda: (runs.append(1), orig())[-1]
    provider.set_occupied({0})
    provider.set_occupied({0, 1})
    provider.set_occupied({1})          # three rapid nudges, one pending tick
    qapp.processEvents()
    assert len(runs) == 1               # collapsed to a single reconcile
    assert c._visible_cells == {1}      # final occupancy, not an intermediate
