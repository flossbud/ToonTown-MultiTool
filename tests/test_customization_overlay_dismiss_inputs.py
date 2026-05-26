"""Dismissal-input contract: Esc / Cancel / Close X / backdrop."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeManager:
    def __init__(self): self._store = {}
    def get(self, g, n): return dict(self._store.get((g, n), {}))
    def set(self, g, n, c): self._store[(g, n)] = dict(c)


def _open_overlay(qapp):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(0, "ttr", "Flossbud", _FakeManager(), None, None, None)
    return overlay, parent


def test_esc_triggers_request_close(qapp):
    overlay, _parent = _open_overlay(qapp)
    esc_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    overlay.keyPressEvent(esc_event)
    assert not overlay.isVisible()  # clean draft -> closes immediately


def test_close_x_triggers_request_close(qapp):
    overlay, _parent = _open_overlay(qapp)
    overlay._panel.close_btn.click()
    assert not overlay.isVisible()


def test_cancel_button_triggers_request_close(qapp):
    overlay, _parent = _open_overlay(qapp)
    overlay._panel.cancel_btn.click()
    assert not overlay.isVisible()


def test_backdrop_click_is_noop(qapp):
    """Clicking the dim backdrop area outside the panel must NOT
    dismiss the overlay."""
    overlay, _parent = _open_overlay(qapp)
    # Synthesize a press well outside the panel rect.
    panel_rect = overlay._panel.geometry()
    out_x = max(0, panel_rect.x() - 20)
    out_y = max(0, panel_rect.y() - 20)
    pos = QPointF(float(out_x), float(out_y))
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        pos, pos, pos,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    QApplication.sendEvent(overlay, press)
    assert overlay.isVisible(), "backdrop click must not dismiss the overlay"
