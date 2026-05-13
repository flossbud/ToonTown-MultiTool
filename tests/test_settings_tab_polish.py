"""Tests for the Settings tab polish pass (2026-05-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_section_block_has_drop_shadow_after_apply_theme(qapp):
    """_SectionBlock attaches a QGraphicsDropShadowEffect on apply_theme."""
    from tabs.settings_tab import SettingsGroup
    from utils.theme_manager import get_theme_colors

    g = SettingsGroup("General")
    g.apply_theme(get_theme_colors(is_dark=True), True)

    effect = g._block.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    # Soft, low offset — values match apply_card_shadow's defaults.
    assert effect.blurRadius() == 18
    assert effect.offset().y() == 4


def test_section_title_has_letter_spacing(qapp):
    """Section title stylesheet declares letter-spacing: 0.15px."""
    from tabs.settings_tab import SettingsGroup
    from utils.theme_manager import get_theme_colors

    g = SettingsGroup("General")
    g.apply_theme(get_theme_colors(is_dark=True), True)
    assert "letter-spacing: 0.15px" in g.title_label.styleSheet()
    # Weight is the explicit 700, not 'bold'
    assert "font-weight: 700" in g.title_label.styleSheet()


def test_collapsible_header_title_has_letter_spacing(qapp):
    """The collapsible header's title also uses the refined typography."""
    from tabs.settings_tab import CollapsibleSettingsGroup
    from utils.theme_manager import get_theme_colors

    class _FakeSM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    g.apply_theme(get_theme_colors(is_dark=True), True)
    assert "letter-spacing: 0.15px" in g._header.title_label.styleSheet()
    assert "font-weight: 700" in g._header.title_label.styleSheet()


def test_settings_row_hover_flag_toggles_on_enter_leave(qapp):
    """SettingsRow tracks hover state for ambient highlight paint."""
    from tabs.settings_tab import SettingsRow
    from PySide6.QtCore import QEvent

    row = SettingsRow("Label", "")
    assert row._hovered is False

    row.enterEvent(QEvent(QEvent.Enter))
    assert row._hovered is True

    row.leaveEvent(QEvent(QEvent.Leave))
    assert row._hovered is False


def test_settings_row_has_wa_hover_attribute(qapp):
    """WA_Hover must be set so enterEvent/leaveEvent fire."""
    from tabs.settings_tab import SettingsRow
    from PySide6.QtCore import Qt

    row = SettingsRow("Label", "")
    assert row.testAttribute(Qt.WA_Hover) is True
