"""Emitting HotkeyManager.refresh_requested must drive the same refresh path as
the status-bar Refresh button (MultitoonTab._on_refresh_requested -> manual_refresh)."""
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.install_method import InstallMethod
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.SOURCE)
    monkeypatch.setattr("utils.update_checker.UpdateChecker.check_async",
                        lambda self, *, manual: True)
    from main import MultiToonTool
    return MultiToonTool()


def test_refresh_requested_invokes_manual_refresh(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path)
    try:
        called = []
        # _on_refresh_requested calls self.manual_refresh(); spy on that so we
        # verify the full wire refresh_requested -> _on_refresh_requested -> action.
        monkeypatch.setattr(w.multitoon_tab, "manual_refresh", lambda: called.append(1))
        w.hotkey_manager.refresh_requested.emit()
        assert called == [1]
    finally:
        w.close()
