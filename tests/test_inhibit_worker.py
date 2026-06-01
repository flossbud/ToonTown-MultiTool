import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from services._inhibit_worker import InhibitAcquireWorker
from services.sleep_inhibitor import InhibitStatus


def _app():
    # Use QApplication (not QCoreApplication) so the session singleton is
    # widget-capable; the autouse teardown fixture in conftest calls
    # app.topLevelWidgets(), which QCoreApplication lacks.
    return QApplication.instance() or QApplication([])


class FakeInhibitor:
    def __init__(self):
        self.status = InhibitStatus(sleep_blocked=True, method="systemd")

    def acquire(self):
        return "systemd"


class RaisingInhibitor:
    def __init__(self):
        self.status = InhibitStatus(sleep_blocked=True, method="systemd")

    def acquire(self):
        raise RuntimeError("boom")


def test_qthread_finished_signal_is_not_shadowed():
    """The custom signal is `status_ready`, so QThread's built-in finished()
    completion signal must still exist and fire when run() returns."""
    _app()
    worker = InhibitAcquireWorker(FakeInhibitor())
    fired = {"finished": False}
    worker.finished.connect(lambda: fired.update(finished=True))  # QThread builtin
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    worker.wait(2000)
    assert fired["finished"] is True


def _drive(worker, timeout_ms=2000):
    """Run the worker to completion on a local event loop, returning the
    emitted status (or None if it timed out)."""
    captured = {}
    worker.status_ready.connect(lambda st: captured.update(status=st))
    loop = QEventLoop()
    worker.status_ready.connect(loop.quit)
    worker.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    worker.wait(2000)
    return captured.get("status")


def test_worker_emits_status():
    _app()
    status = _drive(InhibitAcquireWorker(FakeInhibitor()))
    assert status is not None
    assert status.sleep_blocked is True
    assert status.method == "systemd"


def test_worker_emits_default_status_on_exception():
    _app()
    status = _drive(InhibitAcquireWorker(RaisingInhibitor()))
    assert status is not None
    # On failure the worker emits a fresh default InhibitStatus, NOT the
    # inhibitor's (stale) optimistic status.
    assert status.sleep_blocked is False
    assert status.method == ""


def _make_tab():
    """Build a bare MultitoonTab without running its heavy __init__."""
    from tabs.multitoon._tab import MultitoonTab

    tab = MultitoonTab.__new__(MultitoonTab)
    tab._inhibit_gen = 0
    tab._inhibit_worker = None
    tab._keep_alive_running = True
    logs = []
    tab.log = lambda m: logs.append(m)
    tab._logs = logs
    return tab


def test_on_inhibit_status_ignores_stale_generation():
    """A late result from a worker that was superseded by release/re-acquire
    must NOT fire the signal or flip the indicator."""
    from tabs.multitoon._tab import MultitoonTab

    _app()
    tab = _make_tab()

    fired = {"signal": 0, "indicator": None}
    tab.keep_alive_inhibit_status = SimpleNamespace(
        emit=lambda st: fired.update(signal=fired["signal"] + 1)
    )
    tab._update_inhibit_indicator = lambda st: fired.update(indicator=st)

    # Generation advanced (a release or re-acquire bumped the counter) while a
    # worker tagged with the previous generation is still in flight.
    tab._inhibit_gen = 5
    blocked = InhibitStatus(sleep_blocked=True, method="systemd")
    MultitoonTab._on_inhibit_status(tab, 4, blocked)

    assert fired["signal"] == 0
    assert fired["indicator"] is None


def test_on_inhibit_status_fires_for_current_generation():
    from tabs.multitoon._tab import MultitoonTab

    _app()
    tab = _make_tab()

    fired = {"signal": 0, "indicator": None}
    tab.keep_alive_inhibit_status = SimpleNamespace(
        emit=lambda st: fired.update(signal=fired["signal"] + 1, last=st)
    )
    tab._update_inhibit_indicator = lambda st: fired.update(indicator=st)

    tab._inhibit_gen = 7
    blocked = InhibitStatus(sleep_blocked=True, method="systemd")
    MultitoonTab._on_inhibit_status(tab, 7, blocked)

    assert fired["signal"] == 1
    assert fired["indicator"] is blocked
    assert any("verified" in m.lower() for m in tab._logs)


# ── Task 6: persistent inline indicator ──────────────────────────────────────


def _make_indicator_tab(running=True):
    """Bare tab with a real indicator label, no heavy __init__."""
    from tabs.multitoon._tab import MultitoonTab

    _app()
    tab = MultitoonTab.__new__(MultitoonTab)
    tab._keep_alive_running = running
    MultitoonTab._build_inhibit_indicator(tab)
    return tab


def test_indicator_shows_blocked_state():
    from tabs.multitoon._tab import MultitoonTab

    tab = _make_indicator_tab(running=True)
    MultitoonTab._update_inhibit_indicator(
        tab, InhibitStatus(sleep_blocked=True, method="systemd")
    )
    lbl = tab._inhibit_indicator
    # Visible (not hidden) and in the non-warning/good state.
    assert lbl.isHidden() is False
    assert "not" not in lbl.text().lower()


def test_indicator_shows_not_blocked_state():
    from tabs.multitoon._tab import MultitoonTab

    tab = _make_indicator_tab(running=True)
    MultitoonTab._update_inhibit_indicator(
        tab, InhibitStatus(sleep_blocked=False, screen_lock_cookie_held=True)
    )
    lbl = tab._inhibit_indicator
    assert lbl.isHidden() is False
    # Warning state text differs from the good state and reads as a warning.
    assert "not" in lbl.text().lower()


def test_indicator_hidden_when_keep_alive_not_running():
    from tabs.multitoon._tab import MultitoonTab

    tab = _make_indicator_tab(running=False)
    MultitoonTab._update_inhibit_indicator(
        tab, InhibitStatus(sleep_blocked=True, method="systemd")
    )
    assert tab._inhibit_indicator.isHidden() is True


def test_indicator_update_is_safe_before_build():
    """Called on an object that never built the label (defensive no-op)."""
    from tabs.multitoon._tab import MultitoonTab

    tab = MultitoonTab.__new__(MultitoonTab)
    tab._keep_alive_running = True
    # No _inhibit_indicator attribute set; must not raise.
    MultitoonTab._update_inhibit_indicator(
        tab, InhibitStatus(sleep_blocked=False)
    )


# ── Task 6: one-time-per-launch warning dialog (main.py gating) ───────────────


class _FakeBox:
    """Records the last QMessageBox constructed + whether exec() ran."""
    instances = []
    Warning = object()
    Ok = object()

    def __init__(self, *a, **k):
        self.icon = None
        self.title = ""
        self.text = ""
        self.executed = False
        _FakeBox.instances.append(self)

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, t):
        self.title = t

    def setText(self, t):
        self.text = t

    def setStandardButtons(self, *a):
        pass

    def exec(self):
        self.executed = True
        return 0


def _make_app_stub():
    """A bare MultiToonTool with only the fields the handler touches."""
    from main import MultiToonTool

    obj = MultiToonTool.__new__(MultiToonTool)
    obj._sleep_warning_shown = False
    return obj


def _patch_box(monkeypatch):
    import main as main_mod

    _FakeBox.instances = []
    # The handler imports QMessageBox locally from PySide6.QtWidgets; patch the
    # symbol the import resolves to.
    import PySide6.QtWidgets as qtw

    monkeypatch.setattr(qtw, "QMessageBox", _FakeBox, raising=True)
    return main_mod


def test_dialog_fires_once_when_sleep_blocked_false(monkeypatch):
    from main import MultiToonTool

    main_mod = _patch_box(monkeypatch)
    obj = _make_app_stub()

    MultiToonTool._on_keep_alive_inhibit_status(
        obj, InhibitStatus(sleep_blocked=False, screen_lock_cookie_held=True)
    )
    assert len(_FakeBox.instances) == 1
    assert _FakeBox.instances[0].executed is True
    assert obj._sleep_warning_shown is True

    # Second failing status must NOT show another dialog.
    MultiToonTool._on_keep_alive_inhibit_status(
        obj, InhibitStatus(sleep_blocked=False)
    )
    assert len(_FakeBox.instances) == 1


def test_dialog_does_not_fire_when_sleep_blocked_true(monkeypatch):
    from main import MultiToonTool

    _patch_box(monkeypatch)
    obj = _make_app_stub()

    MultiToonTool._on_keep_alive_inhibit_status(
        obj, InhibitStatus(sleep_blocked=True, method="systemd")
    )
    assert len(_FakeBox.instances) == 0
    assert obj._sleep_warning_shown is False


def test_dialog_does_not_fire_for_screen_lock_only_failure(monkeypatch):
    """sleep_blocked True but screen-lock cookie absent: sleep IS held, so no
    dialog. Only sleep_blocked is False triggers the warning."""
    from main import MultiToonTool

    _patch_box(monkeypatch)
    obj = _make_app_stub()

    MultiToonTool._on_keep_alive_inhibit_status(
        obj, InhibitStatus(sleep_blocked=True, screen_lock_cookie_held=False)
    )
    assert len(_FakeBox.instances) == 0


def test_dialog_copy_has_no_emdash_and_no_internals(monkeypatch):
    from main import MultiToonTool

    _patch_box(monkeypatch)
    obj = _make_app_stub()
    MultiToonTool._on_keep_alive_inhibit_status(
        obj, InhibitStatus(sleep_blocked=False)
    )
    box = _FakeBox.instances[0]
    blob = (box.title + " " + box.text).lower()
    assert "—" not in (box.title + box.text)  # no em-dash
    for forbidden in ("systemd", "d-bus", "dbus", "logind", "inhibitor", "cookie"):
        assert forbidden not in blob
