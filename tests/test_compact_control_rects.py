# tests/test_compact_control_rects.py
import sys
import pytest
from PySide6.QtCore import QObject, Signal, QRect, QPoint
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


def _assert_shell_controls(compact, cell_index):
    """control_rects(shell) returns the 5 control rects of the slot ROUTED into
    that shell (content_slot), mapped to the shell cell - matching exactly what the
    overlay hosts via slot_widget(shell). This is the contract that broke for a
    permuted (e.g. 2-toon TL+BR) cluster: control_rects is indexed by the SHELL,
    not the logical slot."""
    cell = compact._cells[cell_index]
    root = cell["cell"]
    s = cell.get("content_slot", cell_index)
    tab = compact._tab
    # The content_slot's shared widgets must genuinely live in THIS shell, else
    # mapTo(root) would be nonsense (the bug). Independent of control_rects.
    assert root.isAncestorOf(tab.toon_buttons[s])
    assert root.isAncestorOf(tab.set_selectors[s])
    expected = []
    for w in (tab.toon_buttons[s], tab.chat_buttons[s], tab.click_sync_buttons[s],
              cell["ka_pill"], tab.set_selectors[s]):
        sz = w.size()
        if sz.width() > 0 and sz.height() > 0:
            expected.append(QRect(w.mapTo(root, QPoint(0, 0)), sz))
    rects = compact.control_rects(cell_index)
    assert len(rects) == 5, f"shell {cell_index}: expected 5 rects, got {len(rects)}"
    assert rects == expected, f"shell {cell_index}: {rects} != {expected}"


def test_control_rects_match_shell_content_identity(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        compact = _show_compact(tab, qt_app)
        for shell in range(4):
            _assert_shell_controls(compact, shell)
    finally:
        tab.input_service.shutdown()


def test_control_rects_follow_permuted_shells(qt_app, monkeypatch, tmp_path):
    # Non-contiguous arrangement (the 2-toon TL+BR case): slots routed into
    # non-native shells. control_rects(shell) must follow the shell's content_slot.
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        compact = _show_compact(tab, qt_app)
        compact.apply_cell_permutation([1, 0, 3, 2])  # self-inverse permutation
        for _ in range(6):
            qt_app.processEvents()
        # Each shell now holds the inverse slot's content.
        assert [compact._cells[c]["content_slot"] for c in range(4)] == [1, 0, 3, 2]
        for shell in range(4):
            _assert_shell_controls(compact, shell)
    finally:
        tab.input_service.shutdown()


def test_set_shell_body_opacity_dims_only_the_background_fill(qt_app, monkeypatch, tmp_path):
    # The body tier dims ONLY the card background fill (the extra-translucent
    # tier); the controls and portrait are dimmed uniformly by the surface's
    # content opacity, not here.
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        compact = _show_compact(tab, qt_app)
        cell = compact._cells[0]
        s = cell.get("content_slot", 0)

        compact.set_shell_body_opacity(0, 0.8125)
        assert cell["bg"]._peek_opacity == 0.8125
        # Nothing else is touched by the body tier.
        assert not hasattr(cell["portrait_frame"], "_peek_opacity")
        assert not hasattr(tab.slot_badges[s], "_peek_opacity")
        assert not hasattr(tab.toon_buttons[s], "_peek_opacity")
        assert not hasattr(cell["ka_pill"], "_peek_opacity")

        compact.set_shell_body_opacity(0, 1.0)
        assert cell["bg"]._peek_opacity == 1.0
    finally:
        tab.input_service.shutdown()
