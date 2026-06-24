"""Regression: discarding the customization overlay must not leak edits
into the shared ToonCustomizationsManager's in-memory store.

Reproduces the reported bug where, after Customize -> change -> Discard,
nested-field edits (portrait color/pattern, zoom/rotation) persisted for the
session (visible on F5 refresh) even though they were never saved, while
top-level fields (accent/body/pose) correctly reverted. Root cause was a
shallow copy that aliased the manager's live nested 'portrait' sub-dict; the
overlay's live-preview handlers mutated it in place.

Uses the REAL manager (isolated to a tmp config dir via TTMT_CONFIG_DIR) so
the test exercises the true shared-instance path, not a stub.
"""

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


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _build(qapp, manager, existing=None):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    if existing:
        manager.set("ttr", "Flossbud", existing)
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(0, "ttr", "Flossbud", manager, None, None, None)
    return overlay, parent


def test_discard_does_not_leak_nested_portrait_edits(qapp, isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    # Seed a pre-existing portrait sub-dict (the real scenario: the user
    # already has saved customizations). The expected value below is an
    # INDEPENDENT literal so aliasing can't corrupt the comparison target.
    overlay, _parent = _build(qapp, mgr, existing={"portrait": {"color": "#fff000"}})

    # Edit nested portrait fields via the live-preview handlers, then discard.
    overlay._panel.set_portrait_color("#000000")
    overlay._panel.set_portrait_pattern("polka", "#123456")
    overlay.request_close()  # dirty -> confirm prompt
    overlay._confirm_prompt.discard_btn.click()

    assert not overlay.isVisible()
    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#fff000"}}, (
        "nested portrait edits leaked into the manager on discard"
    )


def test_discard_does_not_leak_zoom_rotation(qapp, isolated_config):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    # A pre-existing portrait sub-dict is what makes setdefault("portrait")
    # return the aliased object that the leak rides on.
    overlay, _parent = _build(qapp, mgr, existing={"portrait": {"color": "#fff000"}})

    # Drive the Toon section's framing transform (zoom/offset/rotate).
    toon = overlay._panel.section("Toon")
    toon.set_transform_from_draft((1.5, 0.0, 0.0, 25.0))
    overlay._panel._on_transform_changed()
    overlay.request_close()
    overlay._confirm_prompt.discard_btn.click()

    assert not overlay.isVisible()
    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#fff000"}}, (
        "zoom/rotation leaked into the manager on discard"
    )


def test_save_still_persists_edits(qapp, isolated_config):
    """The fix must not break the happy path: Save still commits."""
    from utils.toon_customizations_manager import ToonCustomizationsManager
    mgr = ToonCustomizationsManager()
    overlay, _parent = _build(qapp, mgr, existing=None)

    overlay._panel.set_portrait_color("#abcdef")
    overlay.close_and_save()

    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#abcdef"}}
