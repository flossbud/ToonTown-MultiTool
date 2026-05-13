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
