"""Tests for ToonCustomizationDialog (sidebar/preview/save flow)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeManager:
    """In-memory stand-in for ToonCustomizationsManager."""

    def __init__(self):
        self._store: dict[tuple[str, str], dict] = {}

    def get(self, game, name):
        return dict(self._store.get((game, name), {}))

    def set(self, game, name, customization):
        if not customization:
            self._store.pop((game, name), None)
        else:
            self._store[(game, name)] = dict(customization)

    def clear(self, game, name):
        self._store.pop((game, name), None)


def _build(qapp, manager=None, game="ttr", existing=None):
    from utils.widgets.toon_customization_dialog import ToonCustomizationDialog
    mgr = manager or _FakeManager()
    if existing:
        mgr.set(game, "Flossbud", existing)
    dlg = ToonCustomizationDialog(
        game=game, toon_name="Flossbud", manager=mgr,
    )
    return dlg, mgr


def test_dialog_constructs(qapp):
    dlg, _ = _build(qapp)
    assert dlg.windowTitle().endswith("Flossbud")


def test_ttr_has_no_icon_section(qapp):
    dlg, _ = _build(qapp, game="ttr")
    assert "Icon" not in dlg.section_names()


@pytest.mark.xfail(reason="Icon section added in Task 10")
def test_cc_has_icon_section(qapp):
    dlg, _ = _build(qapp, game="cc")
    assert "Icon" in dlg.section_names()


def test_save_writes_draft_to_manager(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_accent("#56c856")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#56c856"}


def test_cancel_does_not_touch_manager(qapp):
    dlg, mgr = _build(qapp, existing={"accent": "#abcdef"})
    dlg.set_accent("#56c856")
    dlg.reject()
    assert mgr.get("ttr", "Flossbud") == {"accent": "#abcdef"}


def test_reset_all_empties_draft(qapp):
    dlg, _ = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    dlg.reset_all()
    assert dlg.draft() == {}


def test_draft_loaded_from_existing(qapp):
    dlg, _ = _build(qapp, existing={"accent": "#56c856"})
    assert dlg.draft() == {"accent": "#56c856"}


def test_set_body(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_body("#101020")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}


def test_set_accent_to_none_removes_field(qapp):
    dlg, mgr = _build(qapp, existing={"accent": "#56c856", "body": "#101020"})
    dlg.set_accent(None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"body": "#101020"}
