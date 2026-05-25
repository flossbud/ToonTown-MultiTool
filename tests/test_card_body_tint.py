"""Tests for the _CardBodyTint overlay widget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_construct_with_color(qapp):
    from utils.widgets.card_body_tint import CardBodyTint
    w = CardBodyTint(QColor("#56c856"))
    assert w.color() == QColor("#56c856")


def test_set_color(qapp):
    from utils.widgets.card_body_tint import CardBodyTint
    w = CardBodyTint(QColor("#56c856"))
    w.set_color(QColor("#ff0000"))
    assert w.color() == QColor("#ff0000")


def test_widget_is_transparent_for_mouse(qapp):
    """Body tint must NOT eat mouse events for the controls beneath it."""
    from PySide6.QtCore import Qt
    from utils.widgets.card_body_tint import CardBodyTint
    w = CardBodyTint(QColor("#56c856"))
    assert w.testAttribute(Qt.WA_TransparentForMouseEvents)
