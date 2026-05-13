"""Pin: the full-UI inactive card view exposes a clickable 'Launch a
game' affordance that, when clicked, asks the parent main window to
navigate to the Launch tab via MultitoonTab.launch_tab_requested."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_inactive_card_has_launch_affordance(qapp, tmp_path, monkeypatch):
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
    tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()
    card = tab._full._cards[0]
    link = card.findChild(QLabel, "full_empty_launch_link")
    assert link is not None, (
        f"Expected QLabel#full_empty_launch_link inside an inactive card; "
        f"labels: {[l.objectName() for l in card.findChildren(QLabel)]}"
    )


def test_clicking_launch_link_emits_launch_tab_requested(qapp, tmp_path, monkeypatch):
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
    tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()
    card = tab._full._cards[0]
    link = card.findChild(QLabel, "full_empty_launch_link")

    fired = []
    tab.launch_tab_requested.connect(lambda: fired.append(True))
    # QLabel.linkActivated fires when an embedded HTML anchor is clicked,
    # but for a plain non-rich-text label we emit via a mousePressEvent.
    # Simulate via the label's linkActivated signal if the implementation
    # uses rich text, otherwise via a synthetic mouse release.
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from PySide6.QtCore import QEvent, QPointF, Qt
    dev = QPointingDevice.primaryPointingDevice()
    pos = QPointF(2, 2)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier, dev)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos,
                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier, dev)
    QApplication.sendEvent(link, press)
    QApplication.sendEvent(link, release)
    assert fired == [True], (
        f"Clicking the launch link should emit launch_tab_requested; "
        f"emissions: {fired!r}"
    )
