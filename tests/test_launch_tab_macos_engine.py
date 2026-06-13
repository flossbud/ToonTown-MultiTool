"""macOS launch_tab engine-path resolution: _get_engine_dir returns the data dir
and the _on_launch preflight no longer false-negatives ('game path not set') for
a real macOS install (binary nested in the .app). sys.platform pinned darwin
(project_platform_branch_breaks_unpinned_tests)."""
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from tabs import launch_tab
from tabs.launch_tab import LaunchTab, AccountSlot


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class _DictSettings:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, key, default=None):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value


class _FakeLauncher(QObject):
    game_launched = Signal(int)
    game_exited = Signal(int, str)
    launch_failed = Signal(str)
    def __init__(self, *a, **k):
        super().__init__()
    def launch(self, *a, **k):
        pass


def _make_nested(data_dir):
    nested = data_dir / "Toontown Rewritten.app" / "Contents" / "MacOS"
    nested.mkdir(parents=True)
    b = nested / "TTREngine"
    b.write_bytes(b"")
    os.chmod(b, 0o755)
    return b


def _make_tab(monkeypatch, request, settings):
    _qapp()
    monkeypatch.setattr(launch_tab, "TTRLauncher", _FakeLauncher, raising=False)
    tab = LaunchTab(settings_manager=settings)
    # __init__ starts a credential-probe QThread; stop it at teardown.
    request.addfinalizer(tab.shutdown)
    return tab


def test_get_engine_dir_darwin_returns_data_dir(tmp_path, monkeypatch, request):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "Toontown Rewritten"
    _make_nested(data_dir)
    settings = _DictSettings({"ttr_engine_dir": str(data_dir)})
    tab = _make_tab(monkeypatch, request, settings)
    assert tab._get_engine_dir("ttr") == str(data_dir)


def test_on_launch_preflight_passes_for_macos_install(tmp_path, monkeypatch, request):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "Toontown Rewritten"
    _make_nested(data_dir)
    settings = _DictSettings({"ttr_engine_dir": str(data_dir)})
    tab = _make_tab(monkeypatch, request, settings)

    tab._slots["ttr"]["a"] = AccountSlot(account_id="a", worker=None, launcher=None)
    monkeypatch.setattr(tab, "_global_index_of", lambda aid: 0)

    class _Acct:
        username = ""   # empty -> flow stops at the username check AFTER preflight
        password = ""
    monkeypatch.setattr(tab.cred_manager, "get_account", lambda i: _Acct())

    msgs = []
    monkeypatch.setattr(tab, "_show_failure_dialog", lambda g, a, m: msgs.append(m))
    monkeypatch.setattr(tab, "_update_status", lambda *a, **k: None)

    tab._on_launch("ttr", "a")

    # Preflight PASSED (binary found in the .app): the flow reached the username
    # check, NOT the engine-path failure.
    assert msgs == ["Missing username. Click Edit."]
