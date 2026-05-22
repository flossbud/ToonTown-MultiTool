"""Regression tests: CC slots must hide TTR-only widgets (laff label,
bean label, chat button). Chat is hidden because cross-game chat is not
yet integrated for CC; laff/bean are hidden because CC log data doesn't
expose them."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from utils.cc_toon_info import CCToonInfo

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return list(self.ttr_window_ids)

    def clear_window_ids(self):
        self.ttr_window_ids = []

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


def _make_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    return MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def test_cc_populated_state_hides_chat_laff_and_bean(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    # Pretend slot 0 corresponds to a known CC window id.
    wid = 12345
    tab.window_manager.ttr_window_ids = [wid]

    # Precondition: chat/laff/bean labels start in the "shown" state.
    # Use isHidden() instead of isVisible() because the tab's parent
    # window isn't actually displayed in offscreen test mode.
    tab.chat_buttons[0].show()
    tab.laff_labels[0].show()
    tab.bean_labels[0].show()
    assert not tab.chat_buttons[0].isHidden(), "precondition: chat shown"

    info = CCToonInfo(
        name="Gecko",
        head_code="rls",
        species_letter="r",
        species_name="RABBIT",
        species_emoji="❓",
        dna_colors=(
            (0.4, 0.6, 0.3),
            (1.0, 1.0, 1.0),
            (0.4, 0.6, 0.3),
            (0.4, 0.6, 0.3),
            (0.4, 0.6, 0.3),
        ),
    )
    tab._apply_cc_toon_info([wid], [info])

    assert tab.chat_buttons[0].isHidden(), "chat must hide for CC slot"
    assert tab.laff_labels[0].isHidden(), "laff must hide for CC slot"
    assert tab.bean_labels[0].isHidden(), "bean must hide for CC slot"


def test_cc_empty_state_hides_chat(qt_app, monkeypatch, tmp_path):
    """The empty-info branch of `_apply_cc_toon_info` already hides
    laff/bean. Chat must also be hidden so a CC window with no data yet
    doesn't show a chat affordance."""
    tab = _make_tab(monkeypatch, tmp_path)
    wid = 12345
    tab.window_manager.ttr_window_ids = [wid]
    tab.chat_buttons[0].show()
    assert not tab.chat_buttons[0].isHidden()

    tab._apply_cc_toon_info([wid], [None])

    assert tab.chat_buttons[0].isHidden(), "chat must hide for CC empty slot"
