"""Regression guard: when the app launches with theme=light, the full-UI
toon cards must render with the light-theme card_toon_bg color, not the
dark variant. The chip-rail audit flagged a suspicion that the full
layout's apply_theme wasn't re-running after theme propagation; this
test pins the contract."""

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
    settings = SettingsManager()
    settings.set("theme", "light")

    from utils.theme_manager import apply_theme, get_theme_colors
    apply_theme(qapp, "light")

    from main import MultiToonTool
    window = MultiToonTool()
    # Switch the multitoon tab into full mode to exercise _full.apply_theme
    window.multitoon_tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()

    expected_card_bg = get_theme_colors(is_dark=False)["card_toon_bg"]
    # Inspect the first full-UI card's stylesheet (or its _inactive_root)
    full = window.multitoon_tab._full
    card0 = full._cards[0]
    assert expected_card_bg.lower() in card0.styleSheet().lower(), (
        f"Expected card_toon_bg {expected_card_bg!r} in card stylesheet; "
        f"got: {card0.styleSheet()!r}"
    )
    window.close()
