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
    return tab


def _seed_slot(tab, launcher, account_id="cc-acct"):
    """Install a CC slot with a fresh worker (so the stale-signal guard in
    _on_login_success passes) and the given launcher, returning the worker."""
    from tabs.launch_tab import AccountSlot
    worker = object()
    tab._slots["cc"][account_id] = AccountSlot(
        account_id=account_id, worker=worker, launcher=launcher)
    return worker


def test_cc_login_success_launches_after_up_to_date(monkeypatch, request):
    class _UpToDate(QObject):
        progress = Signal(str, int); up_to_date = Signal(); patched = Signal(list); failed = Signal(str)
        def verify_and_patch(self, game_dir, token, realm="production"):
            self.up_to_date.emit()
    monkeypatch.setattr(launch_tab, "CCPatcher", _UpToDate, raising=False)

    tab = _make_tab(monkeypatch, request)
    launcher = _FakeLauncher()
    worker = _seed_slot(tab, launcher)

    tab._on_login_success("cc", "cc-acct", worker, "gs-1", "token-1")

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
                        lambda account_id, msg, launcher=None: offered.append((account_id, msg)))
    launcher = _FakeLauncher()
    worker = _seed_slot(tab, launcher)

    tab._on_login_success("cc", "cc-acct", worker, "gs-1", "token-1")

    assert launcher.launched_with is None
    assert offered and offered[0][0] == "cc-acct" and "files broken" in offered[0][1]


class _OpenLauncherBox:
    """QMessageBox stand-in: the user picks "Open official launcher"."""
    Warning = object()
    AcceptRole = object()
    RejectRole = object()

    def __init__(self, *a, **k):
        self._buttons = {}

    def setIcon(self, *_):
        pass

    def setWindowTitle(self, *_):
        pass

    def setText(self, *_):
        pass

    def setInformativeText(self, *_):
        pass

    def addButton(self, text, _role):
        self._buttons[text] = object()
        return self._buttons[text]

    def exec(self):
        pass

    def clickedButton(self):
        return self._buttons["Open official launcher"]


def test_unflagged_fallback_calls_the_runner_directly(monkeypatch, request):
    """With TTMT_GRANDSTAND unset the offer is what it always was: the runner,
    called directly with the settings manager, and no install gate — a gate
    here would prompt on a path that never prompted before."""
    import PySide6.QtWidgets as qtw
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    tab = _make_tab(monkeypatch, request)
    assert not hasattr(tab, "grandstand")
    _seed_slot(tab, _FakeLauncher())
    runner = []
    gate = []
    monkeypatch.setattr(launch_tab, "run_official_cc_launcher",
                        lambda *args, **kwargs: (runner.append((args, kwargs)), True)[1])
    monkeypatch.setattr(launch_tab, "_cc_launch_gate",
                        lambda *args, **kwargs: (gate.append(1), True)[1])
    monkeypatch.setattr(qtw, "QMessageBox", _OpenLauncherBox)

    tab._offer_cc_launcher_fallback("cc-acct", "files broken")

    assert runner == [((tab.settings_manager,), {})]
    assert gate == []
