"""Geometry contract tests for ToonCustomizationOverlay."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeManager:
    def __init__(self):
        self._store = {}
    def get(self, game, name):
        return dict(self._store.get((game, name), {}))
    def set(self, game, name, customization):
        self._store[(game, name)] = dict(customization)


def _open_overlay(qapp, parent_size=(575, 770)):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(*parent_size)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(0, "ttr", "Flossbud", _FakeManager(), None, None, None)
    return overlay, parent


def test_overlay_geometry_mirrors_parent(qapp):
    overlay, parent = _open_overlay(qapp, parent_size=(575, 770))
    assert overlay.rect() == parent.rect()


def test_overlay_geometry_follows_resize(qapp):
    overlay, parent = _open_overlay(qapp, parent_size=(575, 770))
    parent.resize(700, 900)
    overlay._refresh_geometry()
    assert overlay.width() == 700
    assert overlay.height() == 900


def test_panel_centered_in_overlay(qapp):
    overlay, _ = _open_overlay(qapp, parent_size=(575, 770))
    expected_x = (575 - overlay._panel.PANEL_W) // 2
    expected_y = (770 - overlay._panel.PANEL_H) // 2
    assert overlay._panel.x() == max(0, expected_x)
    assert overlay._panel.y() == max(0, expected_y)


def test_panel_responsive_dimensions(qapp):
    """The panel sizes itself to the window instead of staying a fixed
    620x470 modal: clamped to MAX on a large window, available-MARGIN on a
    mid window, and never wider than the overlay on a small one."""
    from utils.widgets.customization_overlay import _Panel

    # Large window -> clamps to the maximum editor size.
    big, _ = _open_overlay(qapp, parent_size=(1200, 1100))
    assert big._panel.width() == _Panel.MAX_W
    assert big._panel.height() == _Panel.MAX_H

    # Mid window -> panel = available - margin (between MIN and MAX).
    mid, _ = _open_overlay(qapp, parent_size=(800, 640))
    assert mid._panel.width() == max(_Panel.MIN_W, 800 - _Panel.MARGIN)

    # Narrow window -> shrinks to fit rather than clipping past the edge.
    small, _ = _open_overlay(qapp, parent_size=(575, 770))
    assert small._panel.width() <= 575 - 16


def test_pill_row_contents_match_ttr(qapp):
    overlay, _ = _open_overlay(qapp)
    names = [
        overlay._panel._pill_group.button(i).text()
        for i in range(len(overlay._panel.section_names()))
    ]
    assert names == ["Toon", "Card", "Portrait"]


def test_pill_row_contents_match_cc(qapp):
    """CC uses no nav pills; section_names() is empty and pill_group has no buttons."""
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    from PySide6.QtGui import QColor
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(
        0, "cc", "Flossbud", _FakeManager(),
        None, QColor("#d9a04e"), "dog",
    )
    assert overlay._panel.section_names() == []
    assert len(overlay._panel._pill_group.buttons()) == 0
