"""Pin: the Service idle label uses the theme's status_idle_text color
(not text_muted or status_idle_bg). The audit flagged it as washed-out;
this test forces the contract."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_service_idle_label_uses_status_idle_text(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    from utils.theme_manager import get_theme_colors

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
    # The idle text color is applied to the inner QLabel via set_text_color().
    # Check the label's stylesheet (not the QFrame's) for the token.
    dark = get_theme_colors(is_dark=True)
    label_ss = tab.status_bar.label.styleSheet()
    assert dark["status_idle_text"].lower() in label_ss.lower() or \
           dark["status_idle_text"].upper() in label_ss, (
        f"status_bar label stylesheet should reference status_idle_text "
        f"({dark['status_idle_text']}); got: {label_ss!r}"
    )
    # Italic font-style should not appear in the status bar label's QSS.
    assert "font-style: italic" not in label_ss.lower(), (
        f"Service idle label should not use italic; got: {label_ss!r}"
    )
