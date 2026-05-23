"""Tests for the new SettingsField (row) and SettingsPanel (container)."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ── SettingsField ────────────────────────────────────────────────────────


def test_field_renders_label_only(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    assert field.label_widget.text() == "Theme"
    assert field.helper_widget is None


def test_field_renders_label_with_helper(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme", helper="Switches between dark and light.")
    assert field.label_widget.text() == "Theme"
    assert field.helper_widget is not None
    assert field.helper_widget.text() == "Switches between dark and light."


def test_field_set_control_attaches_widget(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    btn = QPushButton("Browse")
    field.set_control(btn)
    # Control widget is reachable through the field for theming and access.
    assert field.control_widget is btn
    # And actually placed in the layout (parent set to the field).
    assert btn.parentWidget() is field


def test_field_is_last_property_default_false(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    assert field.is_last is False


def test_field_set_is_last_updates_property(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    field.set_is_last(True)
    assert field.is_last is True


def test_field_apply_theme_styles_labels(qapp):
    from tabs.settings_tab import SettingsField
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(is_dark=True)
    field = SettingsField("Theme", helper="Helper text.")
    field.apply_theme(c, is_dark=True)
    # text_primary should be applied to the main label.
    assert c["text_primary"] in field.label_widget.styleSheet()
    # text_muted should be applied to the helper.
    assert c["text_muted"] in field.helper_widget.styleSheet()


# ── SettingsPanel ────────────────────────────────────────────────────────


def test_panel_neutral_stripe_default(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="General")
    assert panel.stripe_kind == "neutral"


def test_panel_ttr_stripe(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Toontown Rewritten", stripe="ttr")
    assert panel.stripe_kind == "ttr"


def test_panel_cc_stripe(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Corporate Clash", stripe="cc")
    assert panel.stripe_kind == "cc"


def test_panel_header_renders_title_and_sub(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Games", sub="Subtitle here.")
    assert panel.title_label.text() == "Games"
    assert panel.sub_label is not None
    assert panel.sub_label.text() == "Subtitle here."


def test_panel_header_no_sub_label_when_omitted(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Games")
    assert panel.sub_label is None


def test_panel_logo_loaded_when_path_provided(qapp, tmp_path):
    """Panels with a logo path display the logo at 40x40."""
    from tabs.settings_tab import SettingsPanel
    # Use the real bundled asset.
    asset = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "ttr.png",
    )
    panel = SettingsPanel(title="TTR", stripe="ttr", logo_path=asset)
    assert panel.logo_label is not None
    pm = panel.logo_label.pixmap()
    assert pm is not None and not pm.isNull()
    # Pixmap scaled to 40 on the long edge (KeepAspectRatio).
    assert max(pm.width(), pm.height()) == 40


def test_panel_no_logo_when_path_omitted(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="General")
    assert panel.logo_label is None


def test_panel_add_field_appends_and_marks_last(qapp):
    from tabs.settings_tab import SettingsPanel, SettingsField
    panel = SettingsPanel(title="General")
    f1 = SettingsField("Theme")
    f2 = SettingsField("Max accounts")
    panel.add_field(f1)
    panel.add_field(f2)
    # Both fields in the panel's tracking list.
    assert panel.fields == [f1, f2]
    # Only the last one has is_last True.
    assert f1.is_last is False
    assert f2.is_last is True


def test_panel_add_header_button_renders_on_right(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr")
    browse = QPushButton("Browse")
    panel.add_header_button(browse)
    # Header button is reachable for theming.
    assert browse in panel.header_buttons
    assert browse.parentWidget() is panel.header_widget


def test_panel_apply_theme_does_not_crash(qapp):
    from tabs.settings_tab import SettingsPanel, SettingsField
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(is_dark=True)
    panel = SettingsPanel(title="Games", stripe="ttr", sub="x")
    panel.add_field(SettingsField("Field A"))
    panel.add_field(SettingsField("Field B", helper="helper"))
    panel.apply_theme(c, is_dark=True)


# ── SettingsPanel.set_sub ────────────────────────────────────────────────


def test_panel_set_sub_creates_label_when_absent(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr")
    assert panel.sub_label is None
    panel.set_sub("~/games/ttr")
    assert panel.sub_label is not None
    assert panel.sub_label.text() == "~/games/ttr"


def test_panel_set_sub_replaces_existing_text(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr", sub="initial")
    panel.set_sub("updated")
    assert panel.sub_label.text() == "updated"


def test_panel_set_sub_rich_text_format(qapp):
    from PySide6.QtCore import Qt as _Qt
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="CC", stripe="cc", sub=" ")
    panel.set_sub("<span style='color:red'>x</span>", rich_text=True)
    assert panel.sub_label.textFormat() == _Qt.RichText
    panel.set_sub("plain path", rich_text=False)
    assert panel.sub_label.textFormat() == _Qt.PlainText


def test_panel_set_sub_color_override_applied(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="X", stripe="neutral", sub="x")
    panel.set_sub("error path", color_override="#E05252")
    assert "#E05252" in panel.sub_label.styleSheet()


def test_panel_set_sub_runtime_create_resizes_header(qapp):
    """Regression: a panel built without sub must grow its header when set_sub
    is later called, so the sub label is not visually clipped."""
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="X", stripe="neutral")  # no sub
    initial_height = panel.header_widget.height()
    panel.set_sub("late-added sub")
    assert panel.header_widget.height() > initial_height
