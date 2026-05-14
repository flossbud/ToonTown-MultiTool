"""Tests for utils/widgets/auto_hide_scrollbar.py — modern scrollbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QScrollBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_construction_returns_qscrollbar_subclass(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    assert isinstance(bar, QScrollBar)
    bar.deleteLater()
