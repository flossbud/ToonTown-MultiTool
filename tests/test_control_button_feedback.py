# tests/test_control_button_feedback.py
import sys
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
import utils.motion as motion
from utils.widgets.scale_press import ScalePushButton


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


def test_all_four_toggles_are_scale_press_buttons(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        for i in range(4):
            assert isinstance(tab.toon_buttons[i], ScalePushButton)
            assert isinstance(tab.chat_buttons[i], ScalePushButton)
            assert isinstance(tab.click_sync_buttons[i], ScalePushButton)
            assert isinstance(tab.keep_alive_buttons[i], ScalePushButton)
    finally:
        tab.input_service.shutdown()


def test_keep_alive_button_press_scales_and_paints(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        qt_app.processEvents()
        ka = tab.keep_alive_buttons[0]
        ka.setFixedSize(32, 32)
        ka.show()
        qt_app.processEvents()
        ka.pressed.emit()
        assert ka.paint_scale == pytest.approx(ScalePushButton.PRESS_SCALE)
        ka.repaint()               # exercises the scaled custom paintEvent, no crash
        ka.released.emit()
        assert ka.paint_scale == pytest.approx(1.0)
    finally:
        tab.input_service.shutdown()
