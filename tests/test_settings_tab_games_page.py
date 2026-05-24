"""Tests for the Games category page (TTR + CC panels)."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings_manager():
    class _Stub:
        def __init__(self):
            self._d = {}
            self._listeners = []

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
            for fn in list(self._listeners):
                fn(key, value)

        def on_change(self, fn):
            self._listeners.append(fn)

    return _Stub()


def test_games_page_has_ttr_and_cc_panels(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, SettingsPanel
    tab = SettingsTab(settings_manager)
    panels = tab.pages["games"].findChildren(SettingsPanel)
    by_kind = {p.stripe_kind: p for p in panels}
    assert "ttr" in by_kind
    assert "cc" in by_kind
    assert by_kind["ttr"].title_label.text() == "Toontown Rewritten"
    assert by_kind["cc"].title_label.text() == "Corporate Clash"


def test_ttr_panel_has_companion_app_toggle(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, SettingsField, Switch
    tab = SettingsTab(settings_manager)
    # Look for a SettingsField with the Companion App label inside the Games page.
    field = None
    for f in tab.pages["games"].findChildren(SettingsField):
        if f.label_widget.text() == "TTR Companion App":
            field = f
            break
    assert field is not None
    assert isinstance(field.control_widget, Switch)
    field.control_widget.setChecked(False)
    assert settings_manager.get("enable_companion_app") is False


def test_cc_panel_has_hide_console_toggle(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, SettingsField, Switch
    from utils.settings_keys import CC_HIDE_LAUNCH_CONSOLE
    settings_manager.set(CC_HIDE_LAUNCH_CONSOLE, True)
    tab = SettingsTab(settings_manager)
    field = None
    for f in tab.pages["games"].findChildren(SettingsField):
        if f.label_widget.text() == "Hide CC launch console":
            field = f
            break
    assert field is not None
    assert isinstance(field.control_widget, Switch)
    field.control_widget.setChecked(False)
    assert settings_manager.get(CC_HIDE_LAUNCH_CONSOLE) is False


def test_cc_panel_external_log_directory_clear(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.settings_keys import CC_EXTERNAL_LOG_DIR
    settings_manager.set(CC_EXTERNAL_LOG_DIR, "/tmp/some/path")
    tab = SettingsTab(settings_manager)
    # The Clear button on the external-log row clears the setting.
    btn = None
    for b in tab.pages["games"].findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton):
        if b.text() == "Clear":
            btn = b
            break
    assert btn is not None
    btn.click()
    assert settings_manager.get(CC_EXTERNAL_LOG_DIR) == ""


def test_cc_panel_external_log_helper_updates_on_browse_and_clear(qapp, settings_manager, monkeypatch):
    """Browse and Clear update the helper text so users see the current value."""
    from tabs.settings_tab import SettingsTab, SettingsField
    from utils.settings_keys import CC_EXTERNAL_LOG_DIR
    from PySide6.QtWidgets import QFileDialog
    settings_manager.set(CC_EXTERNAL_LOG_DIR, "")
    tab = SettingsTab(settings_manager)
    field = None
    for f in tab.pages["games"].findChildren(SettingsField):
        if f.label_widget.text() == "External CC log directory (advanced)":
            field = f
            break
    assert field is not None and field.helper_widget is not None

    # Initially shows the auto state.
    assert "auto-detection" in field.helper_widget.text().lower()

    # Stub QFileDialog to return a path.
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *args, **kwargs: "/tmp/cc-logs",
    )
    tab._on_ext_log_browse()
    assert "/tmp/cc-logs" in field.helper_widget.text()
    assert settings_manager.get(CC_EXTERNAL_LOG_DIR) == "/tmp/cc-logs"

    # Clear restores the auto state.
    tab._on_ext_log_clear()
    assert "auto" in field.helper_widget.text().lower()
    assert settings_manager.get(CC_EXTERNAL_LOG_DIR) == ""


def test_ttr_panel_uses_brand_logo(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, SettingsPanel
    tab = SettingsTab(settings_manager)
    ttr_panel = next(p for p in tab.pages["games"].findChildren(SettingsPanel)
                     if p.stripe_kind == "ttr")
    assert ttr_panel.logo_label is not None
    pm = ttr_panel.logo_label.pixmap()
    assert pm is not None and not pm.isNull()
