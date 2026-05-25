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


def test_set_portrait_color(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_color("#d9a04e")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {"portrait": {"color": "#d9a04e"}}


def test_set_portrait_color_to_none_removes_color(qapp):
    dlg, mgr = _build(qapp, existing={"portrait": {"color": "#d9a04e"}})
    dlg.set_portrait_color(None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_set_gradient(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_gradient({"start": "#ff0000", "end": "#00ff00"})
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"gradient": {"start": "#ff0000", "end": "#00ff00"}}
    }


def test_set_pattern(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_pattern("dots", "#ffffff")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {"pattern": {"name": "dots", "color": "#ffffff"}}
    }


def test_clear_pattern(qapp):
    dlg, mgr = _build(qapp, existing={
        "portrait": {"pattern": {"name": "dots", "color": "#fff000"}}
    })
    dlg.set_portrait_pattern(None, None)
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {}


def test_portrait_combines_color_pattern(qapp):
    dlg, mgr = _build(qapp)
    dlg.set_portrait_color("#d9a04e")
    dlg.set_portrait_pattern("stripes_diag", "#101020")
    dlg.accept_save()
    assert mgr.get("ttr", "Flossbud") == {
        "portrait": {
            "color": "#d9a04e",
            "pattern": {"name": "stripes_diag", "color": "#101020"},
        }
    }


def test_cc_icon_section_initial_selection(qapp):
    """When CC entry has icon_stem, the Icon section reflects it."""
    dlg, _ = _build(
        qapp, game="cc",
        existing={"icon_stem": "dog"},
    )
    sec = dlg.section("Icon")
    assert sec.selected_stem() == "dog"


def test_cc_icon_section_save(qapp):
    dlg, mgr = _build(qapp, game="cc")
    dlg.set_icon_stem("dog")
    dlg.accept_save()
    assert mgr.get("cc", "Flossbud") == {"icon_stem": "dog"}


def test_cc_icon_set_to_none_removes_field(qapp):
    dlg, mgr = _build(qapp, game="cc", existing={"icon_stem": "dog"})
    dlg.set_icon_stem(None)
    dlg.accept_save()
    assert mgr.get("cc", "Flossbud") == {}
