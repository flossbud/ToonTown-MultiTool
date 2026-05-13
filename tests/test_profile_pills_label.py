"""Pin: the profile-pills row carries a 'PROFILE' label so the round
1-5 buttons read as profile presets rather than unattributed numeric
buttons."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_compact_layout_has_profile_label(qapp, tmp_path, monkeypatch):
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
    label = tab.findChild(QLabel, "profile_pills_label")
    assert label is not None, (
        f"No QLabel named 'profile_pills_label' in multitoon compact tab; "
        f"label texts: {[l.text() for l in tab.findChildren(QLabel)]}"
    )
    assert "PROFILE" in label.text().upper(), (
        f"Profile-pills label should read 'PROFILE'; got {label.text()!r}"
    )
