"""Tests for utils.icon_factory help-icon alias."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_make_help_icon_returns_qicon(qapp):
    from utils.icon_factory import make_help_icon
    icon = make_help_icon(18, QColor("#bbbbbb"))
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_make_help_icon_default_size(qapp):
    from utils.icon_factory import make_help_icon
    icon = make_help_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()
