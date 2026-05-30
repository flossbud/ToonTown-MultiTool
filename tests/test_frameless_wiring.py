import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


class _StubSettings:
    def __init__(self, **kv):
        self._kv = kv
    def get(self, key, default=None):
        return self._kv.get(key, default)
    def set(self, key, value):
        self._kv[key] = value


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_apply_window_chrome_frameless_when_setting_off(qapp):
    from PySide6.QtWidgets import QMainWindow
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    # QMainWindow.__init__ must be called so the C++ QWidget base is
    # initialized; setWindowFlag raises otherwise.
    QMainWindow.__init__(inst)
    inst.settings_manager = _StubSettings(use_system_title_bar=False, hints_enabled=True)
    inst.header = inst._build_header()
    inst._apply_window_chrome()
    assert bool(inst.windowFlags() & Qt.FramelessWindowHint)
    assert inst._chrome is not None


def test_apply_window_chrome_native_when_setting_on(qapp):
    from PySide6.QtWidgets import QMainWindow
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    QMainWindow.__init__(inst)
    inst.settings_manager = _StubSettings(use_system_title_bar=True, hints_enabled=True)
    inst.header = inst._build_header()
    inst._apply_window_chrome()
    assert not bool(inst.windowFlags() & Qt.FramelessWindowHint)
    assert inst._chrome is None
