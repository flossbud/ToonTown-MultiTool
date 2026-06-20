"""Position-based card placement Phase 2: the compact layout routes each slot's
content into the shell of its 2x2 cluster cell (apply_cell_permutation), so a
non-contiguous window arrangement (vertical stack, gapped L-shape) shows the cards
at the matching quadrants. The shells never move or change shape.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
      TTMT_CONFIG_DIR=$(mktemp -d) PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      ./venv/bin/python -m pytest tests/test_compact_cell_permutation.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWM(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

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

    def count_for_game(self, game):
        return 0

    def get_window_geometry(self, wid):
        return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(settings_manager=SettingsManager(), window_manager=_FakeWM())
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_identity_permutation_is_noop(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    c = tab._compact
    c.apply_cell_permutation([0, 1, 2, 3])
    assert c._slot_to_cell == [0, 1, 2, 3]
    for i in range(4):
        assert c._cells[i]["content_slot"] == i
        assert tab.slot_badges[i].parentWidget() is c._cells[i]["portrait_frame"]


def test_vertical_stack_routes_content_to_left_column(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    c = tab._compact
    # stack: slot0->cell0(TL), slot1->cell2(BL); empties slot2->cell1, slot3->cell3
    c.apply_cell_permutation([0, 2, 1, 3])
    assert c._slot_to_cell == [0, 2, 1, 3]
    assert c._cells[0]["content_slot"] == 0   # TL shell holds slot 0 (top window)
    assert c._cells[2]["content_slot"] == 1   # BL shell holds slot 1 (bottom window)
    assert c._cells[1]["content_slot"] == 2
    assert c._cells[3]["content_slot"] == 3
    # slot 1's shared widgets are routed into the BL shell (cell 2)
    assert tab.slot_badges[1].parentWidget() is c._cells[2]["portrait_frame"]
    assert tab.toon_labels[1][1].parentWidget() is c._cells[2]["portrait_frame"]
    assert c._cells[2]["cell"].isAncestorOf(tab.toon_buttons[1])
    # and cell 0 still holds slot 0
    assert tab.slot_badges[0].parentWidget() is c._cells[0]["portrait_frame"]


def test_permutation_then_identity_restores(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    c = tab._compact
    c.apply_cell_permutation([0, 2, 1, 3])
    c.apply_cell_permutation([0, 1, 2, 3])
    assert c._slot_to_cell == [0, 1, 2, 3]
    for i in range(4):
        assert c._cells[i]["content_slot"] == i
        assert tab.slot_badges[i].parentWidget() is c._cells[i]["portrait_frame"]


def test_malformed_permutation_is_ignored(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    c = tab._compact
    c.apply_cell_permutation([0, 0, 1, 2])   # not a bijection -> ignored
    assert c._slot_to_cell == [0, 1, 2, 3]
    c.apply_cell_permutation([0, 1])          # wrong length -> ignored
    assert c._slot_to_cell == [0, 1, 2, 3]


def test_cell_assignment_signal_reroutes_compact(qapp, tmp_path, monkeypatch):
    """The window manager's cell_assignment_changed signal drives the compact
    layout's re-routing (the wiring in MultitoonTab)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.window_manager.cell_assignment_changed.emit([0, 2, 1, 3])
    qapp.processEvents()
    assert tab._compact._slot_to_cell == [0, 2, 1, 3]
    assert tab.slot_badges[1].parentWidget() is tab._compact._cells[2]["portrait_frame"]
