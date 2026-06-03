"""TTR launch must run the patcher before launching the engine."""

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
    monkeypatch.setattr(launch_tab, "TTRLauncher", _FakeLauncher, raising=False)
    tab = LaunchTab(settings_manager=_StubSettings())
    # LaunchTab.__init__ starts a credential-probe QThread; stop it at teardown
    # so the process doesn't abort with "QThread: Destroyed while running".
    request.addfinalizer(tab.shutdown)
    return tab


def _seed_slot(tab, launcher, account_id="ttr-acct"):
    """Install a TTR slot with a fresh worker (so the stale-signal guard in
    _on_login_success passes) and the given launcher, returning the worker the
    caller must pass to _on_login_success."""
    from tabs.launch_tab import AccountSlot
    worker = object()
    slot = AccountSlot(account_id=account_id, worker=worker, launcher=launcher)
    tab._slots["ttr"][account_id] = slot
    return worker


def test_ttr_login_success_launches_after_up_to_date(monkeypatch, request):
    class _UpToDatePatcher(QObject):
        progress = Signal(str, int)
        up_to_date = Signal()
        patched = Signal(list)
        failed = Signal(str)
        def verify_and_patch(self, engine_dir):
            self.up_to_date.emit()   # synchronous for the test
    monkeypatch.setattr(launch_tab, "TTRPatcher", _UpToDatePatcher, raising=False)

    tab = _make_tab(monkeypatch, request)
    monkeypatch.setattr(tab, "_get_engine_dir", lambda game: "/engine/dir")
    launcher = _FakeLauncher()
    worker = _seed_slot(tab, launcher)

    tab._on_login_success("ttr", "ttr-acct", worker, "gameserver-1", "cookie-1")

    assert launcher.launched_with is not None
    assert launcher.launched_with[0] == ("gameserver-1", "cookie-1", "/engine/dir")


def test_ttr_login_success_launches_after_patched(monkeypatch, request):
    """The real-world case: files were stale, the patcher updated them, then
    the engine launches. Also logs which files were updated."""
    class _PatchedPatcher(QObject):
        progress = Signal(str, int)
        up_to_date = Signal()
        patched = Signal(list)
        failed = Signal(str)
        def verify_and_patch(self, engine_dir):
            self.patched.emit(["phase_14.mf"])
    monkeypatch.setattr(launch_tab, "TTRPatcher", _PatchedPatcher, raising=False)

    tab = _make_tab(monkeypatch, request)
    monkeypatch.setattr(tab, "_get_engine_dir", lambda game: "/engine/dir")
    logs = []
    monkeypatch.setattr(tab, "log", lambda msg: logs.append(msg))
    launcher = _FakeLauncher()
    worker = _seed_slot(tab, launcher)

    tab._on_login_success("ttr", "ttr-acct", worker, "gameserver-1", "cookie-1")

    assert launcher.launched_with is not None
    assert launcher.launched_with[0] == ("gameserver-1", "cookie-1", "/engine/dir")
    assert any("phase_14.mf" in m for m in logs)


def test_ttr_stale_patcher_up_to_date_does_not_launch_old_launcher(monkeypatch, request):
    """A superseded patcher finishing after a relaunch must not launch the old
    launcher (the _go stale-guard)."""
    holder = {}
    class _DeferredPatcher(QObject):
        progress = Signal(str, int); up_to_date = Signal(); patched = Signal(list); failed = Signal(str)
        def verify_and_patch(self, engine_dir):
            holder["patcher"] = self  # capture; do not emit yet
    monkeypatch.setattr(launch_tab, "TTRPatcher", _DeferredPatcher, raising=False)

    tab = _make_tab(monkeypatch, request)
    monkeypatch.setattr(tab, "_get_engine_dir", lambda game: "/engine/dir")
    old_launcher = _FakeLauncher()
    worker = _seed_slot(tab, old_launcher)
    tab._on_login_success("ttr", "ttr-acct", worker, "gs", "ck")  # _go bound to old_launcher

    # Relaunch reassigns the slot's launcher.
    new_launcher = _FakeLauncher()
    tab._slots["ttr"]["ttr-acct"].launcher = new_launcher

    holder["patcher"].up_to_date.emit()  # stale patcher finishes
    assert old_launcher.launched_with is None  # _go is a no-op


def test_ttr_login_success_aborts_launch_on_patch_failure(monkeypatch, request):
    class _FailingPatcher(QObject):
        progress = Signal(str, int)
        up_to_date = Signal()
        patched = Signal(list)
        failed = Signal(str)
        def verify_and_patch(self, engine_dir):
            self.failed.emit("files broken")
    monkeypatch.setattr(launch_tab, "TTRPatcher", _FailingPatcher, raising=False)

    tab = _make_tab(monkeypatch, request)
    monkeypatch.setattr(tab, "_get_engine_dir", lambda game: "/engine/dir")
    failures = []
    monkeypatch.setattr(tab, "_on_launcher_failed",
                        lambda game, account_id, launcher, msg: failures.append((game, account_id, msg)))
    launcher = _FakeLauncher()
    worker = _seed_slot(tab, launcher)

    tab._on_login_success("ttr", "ttr-acct", worker, "gameserver-1", "cookie-1")

    assert launcher.launched_with is None       # never launched
    assert failures and failures[0][0] == "ttr" and "files broken" in failures[0][2]
