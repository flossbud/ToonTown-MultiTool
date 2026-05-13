"""Tests for the Settings tab redesign (2026-05-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_advanced_collapsed_defaults_true(tmp_path, monkeypatch):
    """advanced_collapsed defaults to True on a fresh SettingsManager."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("advanced_collapsed") is True


import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_settings_row_no_sublabel_is_48px(qapp):
    from tabs.settings_tab import SettingsRow
    row = SettingsRow("Label", "")
    assert row.height() == 48


def test_settings_row_with_sublabel_is_60px(qapp):
    from tabs.settings_tab import SettingsRow
    row = SettingsRow("Label", "Sublabel")
    assert row.height() == 60


def test_settings_row_no_first_last_machinery(qapp):
    """The new SettingsRow doesn't track first/last position any more —
    only `is_last_in_block` matters for divider painting."""
    from tabs.settings_tab import SettingsRow
    row = SettingsRow("Label", "")
    assert hasattr(row, "set_last_in_block")
    assert not hasattr(row, "set_position")


def test_settings_group_title_is_sentence_case(qapp):
    """Section titles are sentence case, not uppercase."""
    from tabs.settings_tab import SettingsGroup
    g = SettingsGroup("General")
    assert g.title_label.text() == "General"  # Not "GENERAL"


def test_settings_group_marks_last_row(qapp):
    """SettingsGroup must call set_last_in_block(True) on its last row
    after rows are added, and False on all earlier rows."""
    from tabs.settings_tab import SettingsGroup, SettingsRow
    g = SettingsGroup("Section")
    r1 = SettingsRow("A", "")
    r2 = SettingsRow("B", "")
    r3 = SettingsRow("C", "")
    g.add_row(r1)
    g.add_row(r2)
    g.add_row(r3)
    assert r1._is_last_in_block is False
    assert r2._is_last_in_block is False
    assert r3._is_last_in_block is True


def test_button_row_emits_clicked(qapp):
    from tabs.settings_tab import ButtonRow
    row = ButtonRow("Reset", "Resets all stored data", button_text="Reset")
    fired = []
    row.clicked.connect(lambda: fired.append(True))
    row.button.click()
    assert fired == [True]


def test_button_row_destructive_styling_applied(qapp):
    """destructive=True applies the red-outline style to the button."""
    from tabs.settings_tab import ButtonRow
    row = ButtonRow("Clear", "", button_text="Clear", destructive=True)
    # apply_theme needs to be called so the destructive style attaches
    from utils.theme_manager import get_theme_colors
    row.apply_theme(get_theme_colors(is_dark=True), True)
    style = row.button.styleSheet()
    assert "#ff3b30" in style


def test_button_row_non_destructive_uses_theme_tokens(qapp):
    """The non-destructive path consumes theme tokens — verifies their keys
    aren't accidentally renamed."""
    from tabs.settings_tab import ButtonRow
    from utils.theme_manager import get_theme_colors
    row = ButtonRow("Action", "", button_text="Go", destructive=False)
    c = get_theme_colors(is_dark=True)
    row.apply_theme(c, True)
    style = row.button.styleSheet()
    # All four tokens used in the non-destructive branch must appear.
    assert c["btn_bg"] in style
    assert c["text_secondary"] in style
    assert c["accent_blue"] in style
    assert c["text_on_accent"] in style
    # The destructive red MUST NOT be present.
    assert "#ff3b30" not in style
