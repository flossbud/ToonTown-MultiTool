import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
    def get_window_ids(self): return list(self.ttr_window_ids)
    def get_active_window(self): return None
    def clear_window_ids(self): self.ttr_window_ids = []
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


class _FakeSignal:
    def __init__(self): self._slots = []
    def connect(self, fn): self._slots.append(fn)
    def emit(self):
        for fn in list(self._slots): fn()


class _FakeDialog:
    instances = []
    def __init__(self, affected_toons=None, parent=None):
        self.affected_toons = affected_toons
        self.restart_as_admin = _FakeSignal()
        self.dont_ask_again = _FakeSignal()
        _FakeDialog.instances.append(self)
    def exec(self): return 0


def _make_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    return MultitoonTab(settings_manager=SettingsManager(), window_manager=_FakeWindowManager())


def test_blocked_signal_shows_dialog(qt_app, monkeypatch, tmp_path):
    _FakeDialog.instances = []
    monkeypatch.setattr("utils.widgets.uipi_elevation_dialog.UipiElevationDialog", _FakeDialog)
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        tab._on_uipi_blocked({"window_id": "w2", "toon_index": 1, "targets": [{"window_id": "w2", "toon_index": 1}]})
        assert len(_FakeDialog.instances) == 1
        assert _FakeDialog.instances[0].affected_toons  # affected toons passed through
    finally:
        tab.input_service.shutdown()


def test_restart_invokes_relaunch(qt_app, monkeypatch, tmp_path):
    _FakeDialog.instances = []
    monkeypatch.setattr("utils.widgets.uipi_elevation_dialog.UipiElevationDialog", _FakeDialog)
    calls = []
    monkeypatch.setattr("utils.win32_elevation.relaunch_elevated",
                        lambda **kw: calls.append(kw) or True)
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        tab._on_uipi_blocked({"window_id": "w2", "toon_index": 1, "targets": []})
        dlg = _FakeDialog.instances[0]
        dlg.restart_as_admin.emit()           # simulate clicking Restart as administrator
        assert len(calls) == 1
    finally:
        tab.input_service.shutdown()


def test_uac_cancel_resets_latch(qt_app, monkeypatch, tmp_path):
    _FakeDialog.instances = []
    monkeypatch.setattr("utils.widgets.uipi_elevation_dialog.UipiElevationDialog", _FakeDialog)
    monkeypatch.setattr("utils.win32_elevation.relaunch_elevated", lambda **kw: False)  # UAC canceled
    tab = _make_tab(monkeypatch, tmp_path)
    reset_calls = []
    monkeypatch.setattr(tab.input_service, "reset_uipi_latch", lambda: reset_calls.append(True))
    try:
        tab._on_uipi_blocked({"window_id": "w2", "toon_index": 1, "targets": []})
        _FakeDialog.instances[0].restart_as_admin.emit()
        assert reset_calls == [True]          # cancel re-arms the prompt
    finally:
        tab.input_service.shutdown()


def test_dont_ask_again_persists(qt_app, monkeypatch, tmp_path):
    _FakeDialog.instances = []
    monkeypatch.setattr("utils.widgets.uipi_elevation_dialog.UipiElevationDialog", _FakeDialog)
    tab = _make_tab(monkeypatch, tmp_path)
    try:
        from utils.settings_keys import UIPI_ELEVATION_PROMPT_DISMISSED
        tab._on_uipi_blocked({"window_id": "w2", "toon_index": 1, "targets": []})
        _FakeDialog.instances[0].dont_ask_again.emit()
        assert tab.input_service.settings_manager.get(UIPI_ELEVATION_PROMPT_DISMISSED, False) is True
        # And a subsequent blocked signal does NOT show a new dialog.
        _FakeDialog.instances = []
        tab._on_uipi_blocked({"window_id": "w2", "toon_index": 1, "targets": []})
        assert _FakeDialog.instances == []
    finally:
        tab.input_service.shutdown()
