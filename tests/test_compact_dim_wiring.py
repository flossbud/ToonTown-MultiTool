import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


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

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    # The dim is gated by effects_disabled(); ensure a perf-flag in the ambient
    # env can't flip the assertion.
    monkeypatch.delenv("TTMT_NO_EFFECTS", raising=False)
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_inactive_slot_dims_badge_and_selector(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        tab.apply_visual_state(0)   # no windows -> slot 0 inactive -> dimmed
        assert tab.slot_badges[0]._dimmed is True
        assert tab.set_selectors[0]._dimmed is True
    finally:
        if hasattr(tab, "input_service") and hasattr(tab.input_service, "shutdown"):
            tab.input_service.shutdown()
