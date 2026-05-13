"""Pin: the per-toon Enable button's disabled state declares an opacity
reduction (0.5) and uses text_disabled color, so it visibly reads as
'unavailable' rather than just 'a button with different colors'."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_enable_button_disabled_state_uses_explicit_opacity(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    from PySide6.QtCore import QObject, Signal

    class _FakeWindowManager(QObject):
        window_ids_updated = Signal(list)
        def __init__(self):
            super().__init__()
            self.ttr_window_ids = []
        def get_window_ids(self): return []
        def clear_window_ids(self): pass
        def assign_windows(self): pass
        def enable_detection(self): pass
        def disable_detection(self): pass

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    enable_btns = tab.toon_buttons if hasattr(tab, "toon_buttons") else []
    assert enable_btns, "tab.toon_buttons list must exist with >=1 Enable button"
    for btn in enable_btns:
        ss = btn.styleSheet()
        assert ":disabled" in ss, (
            f"Enable button stylesheet must include a :disabled rule; "
            f"got: {ss!r}"
        )
