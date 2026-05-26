"""Tests for body-tint widget lazy instantiation per slot."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_body_tint_widget_not_created_without_override(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = tab._compact._card_slots[0]
    assert slot.get("body_tint") is None


def test_body_tint_widget_created_when_override_set(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#101020"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    slot = tab._compact._card_slots[0]
    tint = slot.get("body_tint")
    assert tint is not None
    assert tint.color() == QColor("#101020")


def test_body_tint_widget_hidden_when_override_cleared(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#101020"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    tab.customizations.clear("ttr", "Flossbud")
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    slot = tab._compact._card_slots[0]
    tint = slot.get("body_tint")
    # Widget kept (lazy-create, never destroy) but must be hidden.
    if tint is not None:
        assert not tint.isVisible()


def test_border_uses_darkened_body_when_override_set(qapp, tmp_path, monkeypatch):
    """When a body color is set, the header divider and ka_group both
    use darken_hsl(body, 0.4) instead of the theme's border_muted."""
    from utils.color_math import darken_hsl

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#e74a4a"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    expected = darken_hsl(QColor("#e74a4a"), 0.4).name()
    divider = tab._compact._card_slots[0].get("header_divider")
    assert divider is not None
    assert expected in divider.styleSheet()

    ka_group = tab.ka_groups[0]
    assert expected in ka_group.styleSheet()


def test_border_uses_theme_muted_when_body_default(qapp, tmp_path, monkeypatch):
    """With body cleared, both elements fall back to the theme's
    border_muted color."""
    from utils.theme_manager import get_theme_colors, resolve_theme

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    # No body override set.
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    is_dark = resolve_theme(tab.settings_manager) == "dark"
    expected = get_theme_colors(is_dark)["border_muted"]
    divider = tab._compact._card_slots[0].get("header_divider")
    assert divider is not None
    assert expected in divider.styleSheet()

    ka_group = tab.ka_groups[0]
    assert expected in ka_group.styleSheet()


def test_border_reverts_when_body_cleared_after_set(qapp, tmp_path, monkeypatch):
    """Body set then cleared: border must revert to theme color (no
    stale darken color hanging on)."""
    from utils.theme_manager import get_theme_colors, resolve_theme

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#4a8fe7"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    tab.customizations.clear("ttr", "Flossbud")
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    is_dark = resolve_theme(tab.settings_manager) == "dark"
    expected = get_theme_colors(is_dark)["border_muted"]
    divider = tab._compact._card_slots[0].get("header_divider")
    assert divider is not None
    assert expected in divider.styleSheet()
    ka_group = tab.ka_groups[0]
    assert expected in ka_group.styleSheet()


def test_border_survives_theme_refresh(qapp, tmp_path, monkeypatch):
    """After set_card_brand is called a second time (simulating re-branding
    during refresh_theme), the body-derived ka_group border is still the
    darkened body color (not clobbered by theme-wide updates)."""
    from utils.color_math import darken_hsl

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.slot_badges[0].set_game("ttr")
    tab.customizations.set("ttr", "Flossbud", {"body": "#56c856"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    expected = darken_hsl(QColor("#56c856"), 0.4).name()

    # First assertion: body-derived border is set.
    ka_group = tab.ka_groups[0]
    assert expected in ka_group.styleSheet()
    divider = tab._compact._card_slots[0].get("header_divider")
    assert divider is not None
    assert expected in divider.styleSheet()

    # Simulate the refresh_theme re-brand pass: call set_card_brand again
    # for the same slot with the same customization. This verifies that
    # calling set_card_brand multiple times preserves the body-derived
    # border (it's not clobbered by intermediate theme updates).
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    # Second assertion: body-derived border still survives the re-brand.
    assert expected in ka_group.styleSheet()
    assert expected in divider.styleSheet()
