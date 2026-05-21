"""Tests for the ElidedLabel widget used for middle-truncated paths."""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_elided_label_stores_full_text_for_tooltip(qapp):
    from utils.widgets.picker_card import ElidedLabel
    text = "/home/u/.var/app/com.usebottles.bottles/data/.../CorporateClash.exe"
    lbl = ElidedLabel(text)
    assert lbl.toolTip() == text


def test_elided_label_full_text_accessor(qapp):
    from utils.widgets.picker_card import ElidedLabel
    text = "~/some/path"
    lbl = ElidedLabel(text)
    assert lbl.full_text() == text


def test_elided_label_set_full_text_updates_tooltip(qapp):
    from utils.widgets.picker_card import ElidedLabel
    lbl = ElidedLabel("first")
    lbl.set_full_text("second/path")
    assert lbl.full_text() == "second/path"
    assert lbl.toolTip() == "second/path"
