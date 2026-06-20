# tests/test_compact_control_rects.py
import sys
import pytest
from PySide6.QtCore import QObject, Signal, QRect
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

    def get_window_ids(self): return []
    def get_active_window(self): return None
    def clear_window_ids(self): self.ttr_window_ids = []
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def count_for_game(self, g): return 0
    def get_window_geometry(self, wid): return None


def _make_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setattr("tabs.launch_tab.discover_cc_installs", lambda *a, **k: [])
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    return MultitoonTab(settings_manager=SettingsManager(),
                        window_manager=_FakeWindowManager())


def _show_compact(tab, qt_app):
    compact = tab._compact
    tab._stack.setCurrentWidget(compact)
    tab.show()
    for _ in range(6):
        qt_app.processEvents()
    return compact


def _assert_rects_within_correct_cell(compact, slot):
    rects = compact.control_rects(slot)
    assert len(rects) == 5, f"slot {slot}: expected 5 control rects, got {len(rects)}"
    # Slot content lives in shell _slot_to_cell[slot]; rects are relative to it.
    cell = compact._cells[compact._slot_to_cell[slot]]["cell"]
    card_rect = QRect(0, 0, cell.width(), cell.height())
    for r in rects:
        assert r.width() > 0 and r.height() > 0
        # Anchor check: the rect's origin must sit in THIS slot's cell. (We test
        # top-left, not full containment: offscreen the card is not fixed to its
        # base_size the way the real overlay host fixes it, so child widths are
        # unconstrained here - full containment is not a valid invariant in this
        # context. Under the slot->cell bug the origin lands in the wrong cell,
        # which top-left containment catches.)
        assert card_rect.contains(r.topLeft()), f"slot {slot}: {r} origin outside card {card_rect}"


def test_control_rects_returns_five_rects_within_card(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        compact = _show_compact(tab, qt_app)
        for slot in range(4):
            _assert_rects_within_correct_cell(compact, slot)
    finally:
        tab.input_service.shutdown()


def test_control_rects_follows_cell_permutation(qt_app, monkeypatch, tmp_path):
    # Under a non-identity cell permutation, slot N's widgets live in cell
    # _slot_to_cell[N]; control_rects must map to that cell, not self._cells[N].
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        compact = _show_compact(tab, qt_app)
        compact.apply_cell_permutation([1, 0, 3, 2])
        for _ in range(6):
            qt_app.processEvents()
        assert compact._slot_to_cell == [1, 0, 3, 2]
        for slot in range(4):
            _assert_rects_within_correct_cell(compact, slot)
    finally:
        tab.input_service.shutdown()
