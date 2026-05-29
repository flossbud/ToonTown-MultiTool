"""CC launch must run the patcher before launching the game, and offer the
official launcher on hard patch failure."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from tabs import launch_tab
from tabs.launch_tab import LaunchTab


def _qapp():
    return QApplication.instance() or QApplication([])


class _StubSettings:
    def get(self, *a, **k):
        return a[1] if len(a) > 1 else None
    def set(self, *a, **k):
        pass


class _FakeWineInstall:
    exe_path = "/game/dir/CorporateClash.exe"


class _FakeLauncher(QObject):
    game_launched = Signal(int)
    game_exited = Signal(int, str)
    launch_failed = Signal(str)
    def __init__(self, *a, **k):
        super().__init__()
        self.launched_with = None
    def launch(self, *args, **kwargs):
        self.launched_with = (args, kwargs)


def _make_tab(monkeypatch, request):
    _qapp()
    monkeypatch.setattr(launch_tab, "CCLauncher", _FakeLauncher, raising=False)
    tab = LaunchTab(settings_manager=_StubSettings())
    request.addfinalizer(tab.shutdown)
    monkeypatch.setattr(tab, "_build_cc_install", lambda: _FakeWineInstall())
    monkeypatch.setattr(tab, "_game_accounts_with_indices", lambda g: [])
    return tab


def test_cc_login_success_launches_after_up_to_date(monkeypatch, request):
    class _UpToDate(QObject):
        progress = Signal(str, int); up_to_date = Signal(); patched = Signal(list); failed = Signal(str)
        def verify_and_patch(self, game_dir, token, realm="production"):
            self.up_to_date.emit()
    monkeypatch.setattr(launch_tab, "CCPatcher", _UpToDate, raising=False)

    tab = _make_tab(monkeypatch, request)
    launcher = _FakeLauncher()
    tab._launchers["cc"][0] = launcher

    tab._on_login_success("cc", 0, "gs-1", "token-1")

    assert launcher.launched_with is not None
    args, kwargs = launcher.launched_with
    assert args[0] == "gs-1" and args[1] == "token-1"


def test_cc_login_success_aborts_and_offers_launcher_on_failure(monkeypatch, request):
    class _Failing(QObject):
        progress = Signal(str, int); up_to_date = Signal(); patched = Signal(list); failed = Signal(str)
        def verify_and_patch(self, game_dir, token, realm="production"):
            self.failed.emit("files broken")
    monkeypatch.setattr(launch_tab, "CCPatcher", _Failing, raising=False)

    tab = _make_tab(monkeypatch, request)
    offered = []
    monkeypatch.setattr(tab, "_offer_cc_launcher_fallback",
                        lambda section_index, msg: offered.append((section_index, msg)))
    launcher = _FakeLauncher()
    tab._launchers["cc"][0] = launcher

    tab._on_login_success("cc", 0, "gs-1", "token-1")

    assert launcher.launched_with is None
    assert offered and offered[0][0] == 0 and "files broken" in offered[0][1]
