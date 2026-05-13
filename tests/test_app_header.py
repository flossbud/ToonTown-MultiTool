"""Tests for header construction in MultiToonTool.

We bypass MultiToonTool.__init__ (which starts background threads and reads
$HOME-rooted settings) by constructing via __new__ and calling the
_build_header method directly. The method only writes attributes onto self,
so the uninitialized instance is fine for this scope.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def header(qapp):
    """Build a header without running MultiToonTool.__init__."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    return instance._build_header()


def test_header_min_height_is_56(header):
    """Header minimum height grew from 48 to 56 to fit the 46px icon."""
    assert header.minimumHeight() == 56


def test_header_icon_widget_exists_with_expected_size(header):
    """The header has a child QLabel named 'header_icon' sized 46x46."""
    icon_label = header.findChild(QLabel, "header_icon")
    assert icon_label is not None, "header_icon QLabel not found in header"
    assert icon_label.size() == QSize(46, 46)


def test_header_icon_has_pixmap(header):
    """The header icon has a non-null pixmap loaded from _resolve_app_icon."""
    icon_label = header.findChild(QLabel, "header_icon")
    pixmap = icon_label.pixmap()
    assert not pixmap.isNull()
