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


def _drive(worker, timeout_ms=2000):
    """Run the worker to completion on a local event loop, returning the
    emitted status (or None if it timed out)."""
    captured = {}
    worker.finished.connect(lambda st: captured.update(status=st))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
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
