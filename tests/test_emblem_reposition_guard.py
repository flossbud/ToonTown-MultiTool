"""Regression: the emblem must not be repositioned in grid-host coordinates while
it is reparented into a transparent-mode overlay surface.

Root cause of the "emblem vanishes on a toon add/remove" bug: in transparent mode
the emblem widget is reparented OUT of `_grid_host` into an emblem-sized overlay
surface (OverlaySurface.host -> a zero-margin QVBoxLayout). When a toon add/remove
permuted the per-slot cell assignment, WindowManager.cell_assignment_changed ->
_tab._on_cell_assignment_changed -> _compact.apply_cell_permutation ->
_relayout_all -> _position_emblem ran the WINDOWED positioning math
(`_emblem.move(grid_host_center - s/2)`), shoving the reparented emblem outside
its small surface so it disappeared. `_position_emblem` must no-op when the emblem
is not a child of `_grid_host`.

Run in isolation (never the whole tests/ dir, it hangs):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
    TTMT_CONFIG_DIR=$(mktemp -d) PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
    ./venv/bin/python -m pytest tests/test_emblem_reposition_guard.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass

    def get_active_window(self):
        return None


def _build_layout(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab._compact


def _host_in_surface(emblem, qapp):
    """Mimic OverlaySurface.host(): reparent the emblem into an emblem-sized
    surface driven by a zero-margin QVBoxLayout (the transparent-mode state)."""
    side = emblem.width()
    surface = QWidget()
    lay = QVBoxLayout(surface)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    surface.resize(side, side)
    lay.addWidget(emblem)
    lay.activate()
    qapp.processEvents()
    return surface, side


def test_position_emblem_centers_when_child_of_grid_host(qapp, tmp_path, monkeypatch):
    """Windowed mode (emblem IS a child of _grid_host): unchanged - centered."""
    layout = _build_layout(qapp, tmp_path, monkeypatch)
    gh, em = layout._grid_host, layout._emblem
    gh.resize(600, 600)
    assert em.parentWidget() is gh
    em.move(0, 0)
    layout._position_emblem()
    s = em.width()
    assert em.x() == int(300 - s / 2.0) and em.y() == int(300 - s / 2.0)


def test_position_emblem_noop_when_reparented_into_surface(qapp, tmp_path, monkeypatch):
    """Transparent mode (emblem reparented OUT of _grid_host): _position_emblem
    must NOT move it (moving it lands outside the surface -> the emblem vanishes)."""
    layout = _build_layout(qapp, tmp_path, monkeypatch)
    gh, em = layout._grid_host, layout._emblem
    gh.resize(600, 600)                       # large -> a bad move would be obvious
    surface, side = _host_in_surface(em, qapp)
    assert em.parentWidget() is surface and em.parentWidget() is not gh
    before = em.pos()
    layout._position_emblem()
    assert em.pos() == before                 # not moved
    # ...and it stays fully inside its surface bounds.
    assert em.x() >= 0 and em.y() >= 0
    assert em.x() + em.width() <= side + 1 and em.y() + em.height() <= side + 1


def test_relayout_all_does_not_move_reparented_emblem(qapp, tmp_path, monkeypatch):
    """The fix holds through the real caller: _relayout_all() (reached via
    apply_cell_permutation on a toon add/remove) must leave a reparented emblem
    where its surface placed it."""
    layout = _build_layout(qapp, tmp_path, monkeypatch)
    gh, em = layout._grid_host, layout._emblem
    gh.resize(600, 600)
    surface, side = _host_in_surface(em, qapp)
    assert em.parentWidget() is surface
    before = em.pos()
    layout._relayout_all()
    assert em.pos() == before
    # ...and it stays fully inside its surface bounds.
    assert em.x() + em.width() <= side + 1 and em.y() + em.height() <= side + 1
