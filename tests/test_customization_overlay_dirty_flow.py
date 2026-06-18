"""Dirty-state confirm flow tests for ToonCustomizationOverlay."""

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
    # Return parent so callers hold a reference and the C++ parent
    # widget (and its children) is not prematurely GC'd mid-test.
    return overlay, mgr, parent


def test_request_close_clean_hides_immediately(qapp):
    overlay, _, _parent = _build_overlay(qapp)
    overlay.request_close()
    assert not overlay.isVisible()
    assert not overlay._confirm_prompt.isVisible()


def test_request_close_dirty_shows_prompt(qapp):
    overlay, _, _parent = _build_overlay(qapp, existing={"body": "#000000"})
    overlay._panel.set_body("#56c856")
    overlay.request_close()
    assert overlay.isVisible(), "overlay must stay open while prompt is up"
    assert overlay._confirm_prompt.isVisible()


def test_confirm_keep_editing_dismisses_prompt(qapp):
    overlay, _, _parent = _build_overlay(qapp, existing={"body": "#000000"})
    overlay._panel.set_body("#56c856")
    overlay.request_close()
    overlay._confirm_prompt.keep_btn.click()
    assert overlay.isVisible()
    assert not overlay._confirm_prompt.isVisible()
    assert overlay._panel.draft() == {"body": "#56c856"}


def test_confirm_discard_closes_and_does_not_save(qapp):
    overlay, mgr, _parent = _build_overlay(qapp, existing={"body": "#000000"})
    overlay._panel.set_body("#56c856")
    overlay.request_close()
    overlay._confirm_prompt.discard_btn.click()
    assert not overlay.isVisible()
    assert mgr.get("ttr", "Flossbud") == {"body": "#000000"}


def test_save_always_commits_even_when_clean(qapp):
    overlay, mgr, _parent = _build_overlay(qapp, existing={"body": "#000000"})
    overlay.close_and_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#000000"}
    assert not overlay.isVisible()


def test_dirty_when_field_added(qapp):
    overlay, _, _parent = _build_overlay(qapp)
    assert overlay._is_dirty() is False
    overlay._panel.set_body("#56c856")
    assert overlay._is_dirty() is True


def test_dirty_when_field_reverted_to_original(qapp):
    overlay, _, _parent = _build_overlay(qapp, existing={"body": "#000000"})
    overlay._panel.set_body("#56c856")
    assert overlay._is_dirty() is True
    overlay._panel.set_body("#000000")
    assert overlay._is_dirty() is False


def test_confirm_offers_save_keep_discard(qapp):
    overlay, mgr, _parent = _build_overlay(qapp)
    overlay._panel.set_accent("#ff0000")       # make the draft dirty
    overlay.request_close()                     # dirty -> shows confirm
    cp = overlay._confirm_prompt
    labels = {b.text() for b in cp.findChildren(type(cp.keep_btn))}
    assert {"Save", "Keep editing", "Discard"} <= labels
    saved = []
    overlay.customization_changed.connect(lambda s, g: saved.append((s, g)))
    cp.save_btn.click()
    assert saved == [(0, "ttr")]
    assert mgr.get("ttr", "Flossbud").get("accent") == "#ff0000"
