"""Reset-confirm flow tests for ToonCustomizationOverlay."""

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
        if not customization:
            self._store.pop((game, name), None)
        else:
            self._store[(game, name)] = dict(customization)


def _build_overlay(qapp, existing=None):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    mgr = _FakeManager()
    if existing:
        mgr.set("ttr", "Flossbud", existing)
    overlay.open_for(0, "ttr", "Flossbud", mgr, None, None, None)
    return overlay, mgr, parent


def test_reset_all_requires_confirm(qapp):
    overlay, mgr, parent = _build_overlay(qapp, existing={"accent": "#abc123"})
    assert overlay._panel.draft().get("accent") == "#abc123"

    # Trigger Reset all -> a confirm appears, draft NOT yet cleared
    overlay._panel.reset_requested.emit()
    assert overlay._panel.draft().get("accent") == "#abc123", (
        "draft must be unchanged until confirm is clicked"
    )
    assert overlay._reset_confirm.isVisible(), (
        "reset confirm should be visible after emitting reset_requested"
    )

    # Cancel leaves the draft untouched and hides the prompt
    overlay._reset_confirm.cancel_btn.click()
    assert overlay._panel.draft().get("accent") == "#abc123", (
        "draft must be unchanged after Cancel"
    )
    assert not overlay._reset_confirm.isVisible(), (
        "reset confirm should be hidden after Cancel"
    )

    # Reset all again, then CONFIRM -> draft cleared
    overlay._panel.reset_requested.emit()
    overlay._reset_confirm.reset_btn.click()
    assert overlay._panel.draft() == {}, (
        "draft must be empty after Reset confirm"
    )
    assert not overlay._reset_confirm.isVisible(), (
        "reset confirm should be hidden after Reset"
    )


def test_reset_confirm_does_not_close_overlay(qapp):
    """Confirming reset clears the draft but keeps the overlay open."""
    overlay, mgr, parent = _build_overlay(qapp, existing={"accent": "#abc123"})
    overlay._panel.reset_requested.emit()
    overlay._reset_confirm.reset_btn.click()
    assert overlay.isVisible(), "overlay must stay open after reset confirm"


def test_reset_confirm_cancel_overlay_still_open(qapp):
    """Cancelling reset confirm keeps the overlay open with draft intact."""
    overlay, mgr, parent = _build_overlay(qapp, existing={"body": "#ff0000"})
    overlay._panel.reset_requested.emit()
    overlay._reset_confirm.cancel_btn.click()
    assert overlay.isVisible()
    assert overlay._panel.draft().get("body") == "#ff0000"


def test_reset_confirm_independent_of_unsaved_changes_confirm(qapp):
    """The reset confirm and the unsaved-changes confirm are independent;
    triggering reset should NOT show the unsaved-changes prompt."""
    overlay, mgr, parent = _build_overlay(qapp, existing={"body": "#ff0000"})
    overlay._panel.reset_requested.emit()
    assert not overlay._confirm_prompt.isVisible(), (
        "unsaved-changes confirm must not appear when reset is requested"
    )
    assert overlay._reset_confirm.isVisible()
    overlay._reset_confirm.cancel_btn.click()
