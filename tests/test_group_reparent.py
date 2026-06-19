"""Integration tests for the transactional reparent (Task 4.1b).

The OverlayGroupController, given a `card_provider` (the real _CompactLayout),
reparents the REAL pinwheel cards + emblem into the overlay surfaces on enter()
and restores them to their EXACT tab placement on leave(). These tests build a
real MultitoonTab and drive the controller with real OverlaySurfaces (NoOp
backend, so no Xlib display is opened) - the borrowed widgets are LIVE, so the
key invariant is that they are never deleted, never stranded in a dead surface,
and always returned to the tab.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
        TTMT_CONFIG_DIR=$(mktemp -d) \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_group_reparent.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
import shiboken6
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.group_controller import OverlayGroupController
from utils.overlay.surface import CardSurface, EmblemSurface


# ---------------------------------------------------------------------------
# Fixtures / stubs (config + keyring isolated; real card/emblem build path)
# ---------------------------------------------------------------------------
class _FakeWindowManager(QObject):
    """Minimal stand-in for WindowManager (same shape as the other tab tests)."""

    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def get_active_window(self):
        return None

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


class _StubWindow:
    """Records minimize / restore so we can assert the controller drives them.

    The main window is independent of the card reparent (which targets the
    tab's _CompactLayout widgets), so a recording stub keeps the test focused
    on the reparent transaction.
    """

    def __init__(self):
        self.calls: list = []

    def showMinimized(self):
        self.calls.append("showMinimized")

    def showNormal(self):
        self.calls.append("showNormal")


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """A fully-built MultitoonTab (real card/emblem build path) under config +
    keyring isolation. Relies on conftest's autouse input_service shutdown."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    # The launch tab probes for CC installs during build; stub it out so the
    # tab build path is hermetic.
    import tabs.launch_tab
    monkeypatch.setattr(tabs.launch_tab, "discover_cc_installs", lambda *a, **k: [])

    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


class _RealSurfaceFactory:
    """Builds REAL CardSurface/EmblemSurface (NoOp backend) and can be told to
    raise on the Nth build to force a mid-enter, post-capture failure."""

    def __init__(self, backend, fail_on=None):
        self._backend = backend
        self._fail_on = fail_on   # 1-based build index at which to raise
        self._count = 0
        self.created: list = []

    def __call__(self, state):
        self._count += 1
        if self._fail_on is not None and self._count == self._fail_on:
            raise RuntimeError(f"factory boom on surface #{self._count}")
        if state.is_emblem:
            surf = EmblemSurface(backend=self._backend)
        else:
            surf = CardSurface(state.surface_id, backend=self._backend)
        self.created.append(surf)
        return surf


class _HostRaisesCardSurface(CardSurface):
    """A CardSurface whose host() raises (a mid-enter failure AFTER the widget's
    placement is captured but during the reparent)."""

    def host(self, widget):  # noqa: D401 - test double
        raise RuntimeError("host boom")


def _expected_cell(slot: int) -> tuple[int, int]:
    """The (row, col) a card slot occupies in the 2x2 grid (addWidget order)."""
    return (slot // 2, slot % 2)


def _make(tab, fail_on=None, factory=None):
    win = _StubWindow()
    backend = NoOpOverlayBackend()
    if factory is None:
        factory = _RealSurfaceFactory(backend, fail_on=fail_on)
    ctl = OverlayGroupController(
        win, backend=backend, surface_factory=factory, card_provider=tab._compact
    )
    return ctl, factory, win


# ---------------------------------------------------------------------------
# enter(): the real cards + emblem are hosted in the surfaces
# ---------------------------------------------------------------------------
def test_enter_reparents_cards_and_emblem_into_surfaces(qapp, tab):
    compact = tab._compact
    grid = compact._grid
    ctl, factory, win = _make(tab)

    assert ctl.enter() is True
    assert ctl.is_transparent is True
    qapp.processEvents()

    # Each card cell is hosted in its own surface and is GONE from the grid.
    for i in range(4):
        card = compact._cells[i]["cell"]
        assert card.parent() is ctl._surfaces[i], f"card {i} not hosted in its surface"
        assert grid.indexOf(card) == -1, f"card {i} should be removed from the grid"

    # The emblem is hosted in the last (emblem) surface.
    emblem = compact._emblem
    assert emblem.parent() is ctl._surfaces[4]
    assert grid.indexOf(emblem) == -1

    # Main window minimized (never hidden).
    assert "showMinimized" in win.calls

    ctl.leave()  # clean up before fixture teardown


# ---------------------------------------------------------------------------
# leave(): each widget restored EXACTLY, still alive, window restored
# ---------------------------------------------------------------------------
def test_leave_restores_cards_and_emblem_exactly_and_alive(qapp, tab):
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    ctl, factory, win = _make(tab)

    ctl.enter()
    qapp.processEvents()
    ctl.leave()
    qapp.processEvents()

    assert ctl.is_transparent is False
    assert ctl._surfaces == []
    assert ctl._captured == []
    assert "showNormal" in win.calls

    # Every card is back in its EXACT original grid cell, under the grid host,
    # and still alive (never deleted by a destroyed surface).
    for i in range(4):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card), f"card {i} was deleted"
        idx = grid.indexOf(card)
        assert idx >= 0, f"card {i} not back in the grid"
        assert grid.getItemPosition(idx)[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host

    # The emblem is back: manual (not in the grid), parented to the grid host,
    # raised above the cards, still alive.
    emblem = compact._emblem
    assert shiboken6.isValid(emblem), "emblem was deleted"
    assert grid.indexOf(emblem) == -1, "emblem must not become grid-managed"
    assert emblem.parentWidget() is grid_host
    assert compact._is_topmost(emblem), "emblem should be raised above the cards"


def test_enter_leave_round_trip_is_repeatable(qapp, tab):
    """A second enter/leave cycle must behave identically (idempotent restore)."""
    compact = tab._compact
    grid = compact._grid
    ctl, factory, win = _make(tab)

    for _ in range(2):
        assert ctl.enter() is True
        qapp.processEvents()
        for i in range(4):
            assert compact._cells[i]["cell"].parent() is ctl._surfaces[i]
        ctl.leave()
        qapp.processEvents()
        for i in range(4):
            card = compact._cells[i]["cell"]
            assert shiboken6.isValid(card)
            assert grid.getItemPosition(grid.indexOf(card))[:2] == _expected_cell(i)
        assert compact._is_topmost(compact._emblem)


# ---------------------------------------------------------------------------
# FAIL-CLOSED: a borrowed live widget is ALWAYS returned to the tab
# ---------------------------------------------------------------------------
def test_enter_fail_closed_when_factory_raises_restores_borrowed_widgets(qapp, tab):
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    # Factory raises building the 3rd surface (card slot 2): cards 0 and 1 are
    # already captured + hosted and MUST be returned to the tab.
    ctl, factory, win = _make(tab, fail_on=3)

    assert ctl.enter() is False
    assert ctl.is_transparent is False
    assert ctl.is_active is False
    assert ctl._surfaces == []
    assert ctl._captured == []
    qapp.processEvents()

    # ALL cards are back in their exact grid cells, parented to the grid host,
    # alive, and none is left parented to a surface.
    for i in range(4):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card), f"card {i} was deleted"
        idx = grid.indexOf(card)
        assert idx >= 0, f"card {i} not restored to the grid"
        assert grid.getItemPosition(idx)[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host, f"card {i} stranded off the tab"

    # The emblem (never reached) is untouched + alive.
    emblem = compact._emblem
    assert shiboken6.isValid(emblem)
    assert emblem.parentWidget() is grid_host

    # Failure happened before the minimize step -> window untouched.
    assert win.calls == []


def test_enter_fail_closed_when_host_raises_restores_borrowed_widgets(qapp, tab):
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    backend = NoOpOverlayBackend()

    class _Factory:
        def __init__(self):
            self._count = 0
            self.created: list = []

        def __call__(self, state):
            self._count += 1
            # The 3rd surface (card slot 2) raises during host(), after the
            # widget's tab placement has already been captured.
            if self._count == 3:
                surf = _HostRaisesCardSurface(state.surface_id, backend=backend)
            elif state.is_emblem:
                surf = EmblemSurface(backend=backend)
            else:
                surf = CardSurface(state.surface_id, backend=backend)
            self.created.append(surf)
            return surf

    ctl, factory, win = _make(tab, factory=_Factory())

    assert ctl.enter() is False
    assert ctl.is_transparent is False
    assert ctl._surfaces == []
    assert ctl._captured == []
    qapp.processEvents()

    # Cards 0-2 were captured (host raised on #3 AFTER capture) and all land back
    # in the tab; card 3 + emblem were never reached. Every card is alive, in its
    # exact cell, parented to the grid host - not to any surface.
    for i in range(4):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card), f"card {i} was deleted"
        idx = grid.indexOf(card)
        assert idx >= 0, f"card {i} not restored to the grid"
        assert grid.getItemPosition(idx)[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host

    emblem = compact._emblem
    assert shiboken6.isValid(emblem)
    assert emblem.parentWidget() is grid_host
    assert win.calls == []


class _ReleaseRaisesCardSurface(CardSurface):
    """A CardSurface whose release() raises - to exercise the orphan-retention
    path with a LIVE borrowed card (the card must stay alive, not be deleted)."""

    def release(self):  # noqa: D401 - test double
        raise RuntimeError("release boom")


def test_enter_fail_closed_when_emblem_surface_raises_restores_all_cards(qapp, tab):
    """Failure on the LAST (emblem) surface: all four hosted cards restore and
    the emblem (never captured) is left untouched in the tab."""
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    ctl, factory, win = _make(tab, fail_on=5)  # 5th build = the emblem surface

    assert ctl.enter() is False
    assert ctl.is_transparent is False
    assert ctl._surfaces == [] and ctl._captured == []
    qapp.processEvents()

    for i in range(4):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card)
        assert grid.getItemPosition(grid.indexOf(card))[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host
    emblem = compact._emblem
    assert shiboken6.isValid(emblem)
    assert emblem.parentWidget() is grid_host  # never moved
    assert win.calls == []


def test_fail_closed_keeps_card_alive_when_release_raises(qapp, tab):
    """If a surface's release() raises during the fail-closed unwind, its live
    card is NOT deleted: the surface is retained in _orphans (a Python ref keeps
    it + its child alive), while the other cards still restore to the tab."""
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    backend = NoOpOverlayBackend()

    class _Factory:
        def __init__(self):
            self._count = 0
            self.created: list = []

        def __call__(self, state):
            self._count += 1
            if self._count == 4:                       # force fail-closed (card slot 3)
                raise RuntimeError("factory boom on #4")
            if self._count == 1:                       # card slot 0: release will raise
                surf = _ReleaseRaisesCardSurface(state.surface_id, backend=backend)
            elif state.is_emblem:
                surf = EmblemSurface(backend=backend)
            else:
                surf = CardSurface(state.surface_id, backend=backend)
            self.created.append(surf)
            return surf

    ctl, factory, win = _make(tab, factory=_Factory())
    assert ctl.enter() is False
    qapp.processEvents()

    card0 = compact._cells[0]["cell"]
    # card0's surface release() raised -> NOT re-tabbed, but ALIVE and its surface
    # retained so GC cannot destroy it (and delete the card).
    assert shiboken6.isValid(card0), "card 0 must not be deleted"
    assert any(card0.parent() is s for s in ctl._orphans), "card0's surface must be retained"
    # Cards 1 and 2 (captured before the #4 failure) are restored to the tab.
    for i in (1, 2):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card)
        assert grid.getItemPosition(grid.indexOf(card))[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host
    assert ctl.is_transparent is False


def test_leave_robust_when_one_restore_slot_raises(qapp, tab):
    """If restore_slot raises for one widget during leave(), the others still
    restore, the surfaces are still torn down, and the window is restored."""
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()

    real_restore = compact.restore_slot
    card1 = compact._cells[1]["cell"]
    state = {"raised": False}

    def flaky_restore(record):
        if record.widget is card1 and not state["raised"]:
            state["raised"] = True
            raise RuntimeError("restore boom")
        return real_restore(record)

    ctl._card_provider.restore_slot = flaky_restore
    ctl.leave()
    qapp.processEvents()

    assert ctl.is_transparent is False
    assert ctl._surfaces == []
    assert "showNormal" in win.calls
    # card1's restore_slot raised: NOT deleted, and the last-resort re-attach
    # returns it to the tab's widget tree (parent is grid_host) rather than
    # leaving it floating/parentless - even though its exact cell could not be
    # restored (restore_slot, the exact-cell mechanism, is what failed).
    assert shiboken6.isValid(card1)
    assert card1.parentWidget() is grid_host
    # ...and the fallback also restores intrinsic visibility (setParent hides on
    # reparent), so the re-attached card is not stuck hidden.
    assert card1.isHidden() is False
    # The other cards restored to their exact cells.
    for i in (0, 2, 3):
        card = compact._cells[i]["cell"]
        assert shiboken6.isValid(card)
        assert grid.getItemPosition(grid.indexOf(card))[:2] == _expected_cell(i)
        assert card.parentWidget() is grid_host


def test_double_leave_is_idempotent(qapp, tab):
    """A second leave() while already framed is a harmless no-op."""
    ctl, factory, win = _make(tab)
    ctl.enter()
    qapp.processEvents()
    ctl.leave()
    qapp.processEvents()
    n_normal = win.calls.count("showNormal")
    ctl.leave()  # already framed -> no-op
    assert ctl.is_transparent is False
    assert win.calls.count("showNormal") == n_normal  # no extra restore
