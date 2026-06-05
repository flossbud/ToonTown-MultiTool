import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(monkeypatch, tmp_path, show_notice):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.install_method import InstallMethod
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.SOURCE)
    monkeypatch.setattr("utils.update_checker.UpdateChecker.check_async",
                        lambda self, *, manual: True)
    monkeypatch.setattr("utils.win32_integrity.should_show_admin_notice",
                        lambda *a, **k: show_notice)
    from main import MultiToonTool
    return MultiToonTool()


def test_admin_banner_shown_when_gate_true(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        assert hasattr(w, "admin_notice_banner")
        assert not w.admin_notice_banner.isHidden()   # window not shown in test -> use isHidden()
    finally:
        w.close()


def test_admin_banner_hidden_when_gate_false(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path, show_notice=False)
    try:
        assert w.admin_notice_banner.isHidden()
    finally:
        w.close()


def test_restart_calls_relaunch_and_reenables_on_cancel(qapp, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("utils.win32_elevation.relaunch_elevated",
                        lambda **kw: calls.append(kw) or False)   # simulate UAC cancel
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        w.admin_notice_banner.restart_as_admin.emit()
        assert len(calls) == 1
        assert w.admin_notice_banner._restart_btn.isEnabled()     # re-enabled on cancel
        assert not w.admin_notice_banner.isHidden()               # banner stays
    finally:
        w.close()


def test_restart_success_does_not_reenable_button(qapp, monkeypatch, tmp_path):
    # On a successful relaunch the app is shutting down, so the button must NOT be
    # re-enabled (re-enable happens only on UAC cancel). The real relaunch calls
    # on_success_shutdown itself; the stub returns True without calling it, so the
    # window stays alive for the assertion.
    calls = []
    monkeypatch.setattr("utils.win32_elevation.relaunch_elevated",
                        lambda **kw: calls.append(kw) or True)   # simulate success
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        w.admin_notice_banner.restart_as_admin.emit()
        assert len(calls) == 1
        # Bound methods compare equal (==) but are not identical (is) across
        # attribute accesses, so use == to confirm the callback is wired.
        assert calls[0].get("on_success_shutdown") == w._shutdown_and_quit
        assert not w.admin_notice_banner._restart_btn.isEnabled()  # success -> stays disabled
    finally:
        w.close()


def test_dismiss_persists_key_hides_and_independent(qapp, monkeypatch, tmp_path):
    from utils.settings_keys import (
        WINDOWS_ADMIN_NOTICE_DISMISSED, UIPI_ELEVATION_PROMPT_DISMISSED,
    )
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        w.admin_notice_banner.dismissed.emit()
        assert w.settings_manager.get(WINDOWS_ADMIN_NOTICE_DISMISSED, False) is True
        assert w.admin_notice_banner.isHidden()
        # Independence direction 1: dismissing the banner does NOT set the UIPI key.
        assert w.settings_manager.get(UIPI_ELEVATION_PROMPT_DISMISSED, False) is False
    finally:
        w.close()


def test_uipi_key_does_not_set_admin_key(qapp, monkeypatch, tmp_path):
    from utils.settings_keys import (
        WINDOWS_ADMIN_NOTICE_DISMISSED, UIPI_ELEVATION_PROMPT_DISMISSED,
    )
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        # Independence direction 2: setting the proof-modal key does NOT set the admin key.
        w.settings_manager.set(UIPI_ELEVATION_PROMPT_DISMISSED, True)
        assert w.settings_manager.get(WINDOWS_ADMIN_NOTICE_DISMISSED, False) is False
    finally:
        w.close()


def test_admin_banner_ordered_after_update_banner(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path, show_notice=True)
    try:
        layout = w.update_banner.parentWidget().layout()
        ui = layout.indexOf(w.update_banner)
        ai = layout.indexOf(w.admin_notice_banner)
        assert ui != -1 and ai != -1 and ai == ui + 1   # admin banner just below update banner
    finally:
        w.close()
