"""Lifecycle tests for ToonCustomizationOverlay.

Starts with _BackdropBlur in isolation; expanded as tasks land."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _solid_pixmap(w, h, hex_color):
    pix = QPixmap(w, h)
    pix.fill(QColor(hex_color))
    return pix


def test_backdrop_blur_exists(qapp):
    from utils.widgets.customization_overlay import _BackdropBlur
    parent = QWidget()
    parent.resize(400, 300)
    bd = _BackdropBlur(parent)
    assert bd.parentWidget() is parent


def test_backdrop_blur_accepts_source_pixmap(qapp):
    """set_source_pixmap stores a blurred copy of the input. The
    blurred pixmap dimensions match the input (helper preserves
    size)."""
    from utils.widgets.customization_overlay import _BackdropBlur
    parent = QWidget()
    parent.resize(200, 100)
    bd = _BackdropBlur(parent)
    src = _solid_pixmap(200, 100, "#888888")
    bd.set_source_pixmap(src)
    assert bd._blurred is not None
    assert bd._blurred.size() == src.size()


def test_backdrop_blur_dim_color_present(qapp):
    """The widget paints a 40 % black dim on top of the blurred
    pixmap. We can introspect the dim color directly."""
    from utils.widgets.customization_overlay import _BackdropBlur
    bd = _BackdropBlur()
    assert bd.DIM_COLOR.alpha() == int(0.40 * 255)
    assert bd.DIM_COLOR.red() == 0
    assert bd.DIM_COLOR.green() == 0
    assert bd.DIM_COLOR.blue() == 0


def test_panel_has_pinned_dimensions(qapp):
    from utils.widgets.customization_overlay import _Panel
    parent = QWidget()
    parent.resize(575, 770)
    panel = _Panel(parent)
    assert panel.PANEL_W == 543
    assert panel.PANEL_H == 738
    assert panel.HEADER_H == 44
    assert panel.FOOTER_H == 52


def test_panel_has_close_x_button(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.close_btn is not None
    assert panel.close_btn.text() == ""  # icon-only
    assert panel.close_btn.minimumWidth() == 28


def test_panel_has_footer_buttons(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.reset_btn is not None
    assert panel.reset_btn.text() == "Reset all"
    assert panel.cancel_btn is not None
    assert panel.cancel_btn.text() == "Cancel"
    assert panel.save_btn is not None
    assert panel.save_btn.text() == "Save"


def test_panel_pill_row_exists(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.pill_row is not None
    assert panel.section_stack is not None


def test_panel_emits_close_signal(qapp):
    """Clicking the close X emits close_requested."""
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.close_requested.connect(lambda: received.append(True))
    panel.close_btn.click()
    assert received == [True]


def test_panel_emits_cancel_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.cancel_requested.connect(lambda: received.append(True))
    panel.cancel_btn.click()
    assert received == [True]


def test_panel_emits_save_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.save_requested.connect(lambda: received.append(True))
    panel.save_btn.click()
    assert received == [True]


def test_panel_emits_reset_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.reset_requested.connect(lambda: received.append(True))
    panel.reset_btn.click()
    assert received == [True]


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


def _build_panel(qapp, game="ttr", existing=None, dna=None):
    from utils.widgets.customization_overlay import _Panel
    from PySide6.QtGui import QColor
    mgr = _FakeManager()
    if existing:
        mgr.set(game, "Flossbud", existing)
    panel = _Panel()
    panel.populate(
        game=game,
        toon_name="Flossbud",
        manager=mgr,
        dna=dna,
        skin_color=QColor("#d9a04e") if game == "cc" else None,
        auto_stem="dog" if game == "cc" else None,
    )
    return panel, mgr


def test_panel_populate_ttr_section_set(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    names = panel.section_names()
    assert "Toon" in names
    assert "Body" in names
    assert "Accent" in names
    assert "Portrait" in names
    assert "Icon" not in names


def test_panel_populate_cc_section_set(qapp):
    panel, _ = _build_panel(qapp, game="cc")
    names = panel.section_names()
    assert "Icon" in names
    assert "Body" in names
    assert "Accent" in names
    assert "Portrait" in names
    assert "Toon" not in names


def test_panel_pill_buttons_match_sections(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    pill_texts = [
        panel._pill_group.button(i).text()
        for i in range(len(panel.section_names()))
    ]
    assert pill_texts == panel.section_names()


def test_panel_title_includes_toon_name(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    assert "Flossbud" in panel.title_label.text()


def test_panel_set_body_updates_draft(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    panel.set_body("#56c856")
    assert panel.draft() == {"body": "#56c856"}


def test_panel_set_accent_updates_draft(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    panel.set_accent("#56c856")
    assert panel.draft() == {"accent": "#56c856"}


def test_panel_preview_widget_installed(qapp):
    panel, _ = _build_panel(qapp, game="ttr")
    from utils.widgets.card_preview_widget import CardPreviewWidget
    children = panel.preview_host.findChildren(CardPreviewWidget)
    assert len(children) == 1


def test_panel_reset_all_clears_draft(qapp):
    panel, _ = _build_panel(
        qapp, game="ttr",
        existing={"body": "#56c856", "accent": "#abcdef"},
    )
    assert panel.draft() == {"body": "#56c856", "accent": "#abcdef"}
    panel.reset_all()
    assert panel.draft() == {}


def test_overlay_open_for_shows_overlay(qapp):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    mgr = _FakeManager()
    overlay.open_for(
        slot=0, game="ttr", toon_name="Flossbud",
        manager=mgr, dna=None, skin_color=None, auto_stem=None,
    )
    assert overlay.isVisible()
    assert overlay._panel.section_names() != []


def test_overlay_close_and_discard_hides(qapp):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    overlay.open_for(0, "ttr", "Flossbud", _FakeManager(), None, None, None)
    overlay.close_and_discard()
    assert not overlay.isVisible()


def test_overlay_close_and_save_emits_signal(qapp):
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    parent = QWidget()
    parent.resize(575, 770)
    parent.show()
    overlay = ToonCustomizationOverlay(parent)
    overlay._skip_animations_for_test = True
    mgr = _FakeManager()
    received = []
    overlay.customization_changed.connect(
        lambda s, g: received.append((s, g))
    )
    overlay.open_for(2, "ttr", "Flossbud", mgr, None, None, None)
    overlay._panel.set_body("#56c856")
    overlay.close_and_save()
    assert received == [(2, "ttr")]
    assert mgr.get("ttr", "Flossbud") == {"body": "#56c856"}
