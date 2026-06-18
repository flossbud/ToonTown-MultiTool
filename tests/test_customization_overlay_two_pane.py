"""Two-pane layout contract for _Panel (rail + content pane).

Verifies that after the two-pane restructure:
- a rail container with objectName "panelRail" exists
- the preview widget and nav buttons live inside the rail
- the section_stack is the right pane (NOT inside the rail)
- TTR section order is unchanged
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


def _build_overlay(qapp):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    mgr = _FakeManager()
    overlay.open_for(0, "ttr", "Flossbud", mgr, None, None, None)
    return overlay, mgr, parent


def test_rail_container_exists(qapp):
    """The panel must expose a rail container with objectName 'panelRail'
    and a matching self._rail attribute."""
    overlay, _, _parent = _build_overlay(qapp)
    panel = overlay._panel
    rail = panel.findChild(QWidget, "panelRail")
    assert rail is not None
    assert panel._rail is rail


def test_preview_widget_is_inside_rail(qapp):
    """After open_for, the CardPreviewWidget must be a descendant of the
    rail container."""
    from utils.widgets.card_preview_widget import CardPreviewWidget
    overlay, _, _parent = _build_overlay(qapp)
    panel = overlay._panel
    rail = panel.findChild(QWidget, "panelRail")
    assert rail is not None
    preview_widgets = rail.findChildren(CardPreviewWidget)
    assert len(preview_widgets) == 1


def test_nav_buttons_are_inside_rail(qapp):
    """Every nav button registered in _pill_group must be a descendant of
    the rail container."""
    overlay, _, _parent = _build_overlay(qapp)
    panel = overlay._panel
    rail = panel.findChild(QWidget, "panelRail")
    assert rail is not None
    buttons = panel._pill_group.buttons()
    assert len(buttons) > 0
    for btn in buttons:
        w = btn.parentWidget()
        inside_rail = False
        while w is not None:
            if w is rail:
                inside_rail = True
                break
            w = w.parentWidget()
        assert inside_rail, f"nav button '{btn.text()}' is not inside the rail"


def test_section_stack_is_not_inside_rail(qapp):
    """The section_stack must be the right pane - it must NOT be a
    descendant of the rail container."""
    overlay, _, _parent = _build_overlay(qapp)
    panel = overlay._panel
    rail = panel.findChild(QWidget, "panelRail")
    assert rail is not None
    w = panel.section_stack.parentWidget()
    while w is not None:
        assert w is not rail, "section_stack must NOT be inside the rail"
        w = w.parentWidget()


def test_ttr_section_names_order_preserved(qapp):
    """TTR sections must appear in the canonical order established before
    this refactor: Toon, Portrait, Accent, Body."""
    overlay, _, _parent = _build_overlay(qapp)
    panel = overlay._panel
    assert panel.section_names() == ["Toon", "Portrait", "Accent", "Body"]
