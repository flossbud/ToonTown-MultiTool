"""The app.refresh hotkey action must drive the same refresh path as the
status-bar Refresh button (dispatch -> MultitoonTab._on_refresh_requested ->
manual_refresh), and the default refresh binding (platform-dependent: bare
F5 is the Dictation media key on Mac laptop keyboards, so darwin uses a
modifier chord) must resolve to it through the window's hotkey hook."""
import pytest
from PySide6.QtWidgets import QApplication

from utils.hotkey_actions import action_by_id

_REFRESH = action_by_id("app.refresh").default_chord
_REFRESH_MODS = frozenset(p for p in _REFRESH.split("+")
                          if p in ("ctrl", "alt", "shift", "super"))
_REFRESH_KEYS = frozenset(p for p in _REFRESH.split("+")
                          if p not in ("ctrl", "alt", "shift", "super"))


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
    # Keep the test off the live X server: a started provider would install
    # real passive grabs for the default bindings (F5, Ctrl+1..5).
    monkeypatch.setattr("services.global_hotkeys.X11GlobalHotkeys.start",
                        lambda self: False)
    from main import MultiToonTool
    return MultiToonTool()


def test_refresh_action_invokes_manual_refresh(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path)
    try:
        called = []
        # _on_refresh_requested calls self.manual_refresh(); spy on that so we
        # verify the full wire hook -> _on_hotkey_action -> dispatch -> action.
        monkeypatch.setattr(w.multitoon_tab, "manual_refresh", lambda: called.append(1))
        assert w._hotkey_hook(_REFRESH_MODS, _REFRESH_KEYS) == "app.refresh"
        w._on_hotkey_action("app.refresh")
        assert called == [1]
    finally:
        w.close()


def test_hotkey_action_ignored_while_chord_capture_records(qapp, monkeypatch, tmp_path):
    """Provider-side fires bypass the session tap (Carbon), so the dispatch
    itself must drop actions while a Settings capture button is recording -
    re-recording a bound chord must not trigger it."""
    from utils import chord_capture_state
    w = _make_window(monkeypatch, tmp_path)
    try:
        called = []
        monkeypatch.setattr(w.multitoon_tab, "manual_refresh", lambda: called.append(1))
        chord_capture_state.set_active(True)
        try:
            w._on_hotkey_action("app.refresh")
            assert called == []
        finally:
            chord_capture_state.set_active(False)
        w._on_hotkey_action("app.refresh")
        assert called == [1]
    finally:
        w.close()
