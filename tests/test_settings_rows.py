"""SettingsRows: the Settings rows without a SettingsTab (the launchpad
window's Settings sheet uses it). SettingsTab is deleted at cut-over; these
tests pin the shared code on its own."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from utils.settings_keys import KEEP_ALIVE_CONSENT_ACKNOWLEDGED, KEEP_ALIVE_ENABLED
from utils.widgets.settings_rows import SettingsRows, SettingsRowsMixin


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.order = []
        self._cbs = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.order.append((key, value))
        for cb in list(self._cbs):
            cb(key, value)

    def on_change(self, cb):
        self._cbs.append(cb)


def _page():
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.addStretch(1)
    page._panel_layout = lay
    return page


@pytest.fixture
def quiet(monkeypatch):
    """No game discovery on the host machine."""
    import utils.widgets.settings_rows as sr
    monkeypatch.setattr(sr, "find_engine_path", lambda: None)
    monkeypatch.setattr(sr, "find_cc_engine_path", lambda: None)
    monkeypatch.setattr(sr, "discover_cc_installs", lambda: [])
    monkeypatch.setattr("services.cc_login_service.discover_cc_installs", lambda: [])


def test_settings_rows_is_a_qobject_with_the_tab_signals(qapp):
    rows = SettingsRows(_Settings())
    for name in ("debug_visibility_changed", "theme_changed", "input_backend_changed",
                 "clear_credentials_requested", "chat_handling_mode_changed"):
        assert hasattr(rows, name)
    for name in ("set_hotkey_accounts_provider", "set_hotkey_status",
                 "set_update_checker", "apply_picked_install",
                 "get_keep_alive_delay_seconds"):
        assert callable(getattr(rows, name))
    assert isinstance(rows, SettingsRowsMixin)


@pytest.mark.parametrize("builder", [
    "_build_general_page", "_build_games_page", "_build_features_page",
    "_build_advanced_page",
])
def test_every_builder_runs_without_a_settings_tab(qapp, quiet, builder):
    rows = SettingsRows(_Settings())
    page = _page()
    getattr(rows, builder)(page)
    assert page._panel_layout.count() > 1          # cards inserted before the stretch
    rows._apply_rows_theme(True)
    rows._apply_rows_theme(False)


def test_keep_alive_records_consent_before_the_flag(qapp, monkeypatch):
    """The session's keep-alive gate is flag AND consent: a consumer reacting
    to the flag must already see consent recorded."""
    sm = _Settings()
    rows = SettingsRows(sm)
    page = _page()                  # keep the page (and its rows) alive
    rows._build_keep_alive_card(page)
    monkeypatch.setattr(rows, "_show_keep_alive_warning_dialog", lambda: True)
    seen_at_flag = []
    sm.on_change(lambda k, v: seen_at_flag.append(sm.get(KEEP_ALIVE_CONSENT_ACKNOWLEDGED))
                 if k == KEEP_ALIVE_ENABLED and v is True else None)
    rows._on_keep_alive_master_toggle(True)
    keys = [k for k, _ in sm.order]
    assert keys.index(KEEP_ALIVE_CONSENT_ACKNOWLEDGED) < keys.index(KEEP_ALIVE_ENABLED)
    assert seen_at_flag == [True]


def test_keep_alive_declined_records_nothing(qapp, monkeypatch):
    sm = _Settings()
    rows = SettingsRows(sm)
    page = _page()                  # keep the page (and its rows) alive
    rows._build_keep_alive_card(page)
    monkeypatch.setattr(rows, "_show_keep_alive_warning_dialog", lambda: False)
    rows._on_keep_alive_master_toggle(True)
    assert KEEP_ALIVE_ENABLED not in sm.data
    assert KEEP_ALIVE_CONSENT_ACKNOWLEDGED not in sm.data
    assert not rows._ka_master_switch.isChecked()


def test_keep_alive_with_consent_skips_the_dialog(qapp, monkeypatch):
    sm = _Settings({KEEP_ALIVE_CONSENT_ACKNOWLEDGED: True})
    rows = SettingsRows(sm)
    page = _page()                  # keep the page (and its rows) alive
    rows._build_keep_alive_card(page)
    monkeypatch.setattr(rows, "_show_keep_alive_warning_dialog",
                        lambda: pytest.fail("asked again"))
    rows._on_keep_alive_master_toggle(True)
    assert sm.data[KEEP_ALIVE_ENABLED] is True


def test_dialogs_use_the_given_parent(qapp, monkeypatch):
    parent = QWidget()
    rows = SettingsRows(_Settings(), dialog_parent=parent)
    assert rows._dialog_parent() is parent
    assert rows._dialog_window() is parent.window()
    seen = []

    class _Box(QMessageBox):
        def __init__(self, p=None):
            seen.append(p)
            super().__init__(p)

        def exec(self):
            return QMessageBox.Yes

    import utils.widgets.settings_rows as sr
    monkeypatch.setattr(sr, "QMessageBox", _Box)
    fired = []
    rows.clear_credentials_requested.connect(lambda: fired.append(1))
    rows._on_clear_credentials_clicked()
    assert seen == [parent] and fired == [1]
    rows.set_dialog_parent(None)
    assert rows._dialog_window() is None
