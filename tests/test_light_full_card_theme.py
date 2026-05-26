"""Regression guard: when the app launches with theme=light, the full-UI
toon cards must render with the light-theme bg_card color, not the dark
variant. After the compact-clone refactor, full cards expose their chrome
through _card_slots[i]["card"] rather than the old _cards list."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from utils.settings_manager import SettingsManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_full_card_uses_light_theme_card_bg(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    settings = SettingsManager()
    settings.set("theme", "light")

    from utils.theme_manager import apply_theme, get_theme_colors
    apply_theme(qapp, "light")

    from main import MultiToonTool
    window = MultiToonTool()
    window.multitoon_tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()

    expected_card_bg = get_theme_colors(is_dark=False)["bg_card"]
    full = window.multitoon_tab._full
    card0 = full._card_slots[0]["card"]
    assert expected_card_bg.lower() in card0.styleSheet().lower(), (
        f"Expected bg_card {expected_card_bg!r} in card stylesheet; "
        f"got: {card0.styleSheet()!r}"
    )
    window.close()
