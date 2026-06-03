"""LaunchTab loading-state orchestration (keyed by account_id)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QObject, Signal


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWM(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self._counts = {"ttr": 0, "cc": 0}
        self.enabled = False

    def enable_detection(self):
        self.enabled = True

    def count_for_game(self, game):
        return self._counts.get(game, 0)


class _FakeLauncher:
    """Stand-in launcher. The loading machine drives RUNNING via the timer /
    window credit, not via the launcher; is_running() stays False so the
    activity-ring rehydration in _effective_state reads the stored slot state
    rather than short-circuiting to RUNNING."""

    def is_running(self):
        return False


class _SM:
    def get(self, k, d=""): return d
    def set(self, k, v): pass


def _wait(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _make_tab(qapp, monkeypatch, tmp_path, wm, accounts=1):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.credentials_manager import CredentialsManager
    from tabs.launch_tab import LaunchTab
    cm = CredentialsManager()
    cm._probe_complete = True
    for i in range(accounts):
        cm.add_account(label=f"A{i}", username=f"u{i}@e.com", password="", game="cc")
    tab = LaunchTab(credentials_manager=cm, settings_manager=_SM(),
                    window_manager=wm)
    tab._on_keyring_probe_complete(True)  # force the slot grid to build
    assert _wait(lambda: len(tab._slots["cc"]) >= accounts)
    return tab


def _ids(tab, n):
    """Return the first n cc account ids in order."""
    return [a.id for a in tab._ordered_accounts("cc")][:n]


def _launch(tab, account_id, pid):
    """Install a launcher on the slot (so the identity guard passes) and fire
    the game_launched handler the way _make_launchers' lambda would."""
    launcher = _FakeLauncher()
    tab._slots["cc"][account_id].launcher = launcher
    tab._on_game_launched("cc", account_id, launcher, pid)
    return launcher


def _state(tab, account_id):
    return tab._slots["cc"][account_id].state


def test_game_launched_enters_loading_and_enables_detection(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = _FakeWM()
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    _launch(tab, a, 1234)
    assert _state(tab, a) == LoginState.LOADING
    assert wm.enabled is True


def test_window_appearance_promotes_loader(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = _FakeWM()
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    _launch(tab, a, 1234)
    wm._counts["cc"] = 1
    tab._on_windows_changed([])
    assert _state(tab, a) == LoginState.RUNNING


def test_two_loaders_promote_in_fifo_order(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = _FakeWM()
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm, accounts=2)
    a0, a1 = _ids(tab, 2)
    _launch(tab, a0, 1)
    _launch(tab, a1, 2)
    wm._counts["cc"] = 1
    tab._on_windows_changed([])
    assert _state(tab, a0) == LoginState.RUNNING
    assert _state(tab, a1) == LoginState.LOADING
    wm._counts["cc"] = 2
    tab._on_windows_changed([])
    assert _state(tab, a1) == LoginState.RUNNING


def test_preexisting_window_does_not_false_promote(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = _FakeWM()
    wm._counts["cc"] = 1  # a CC window already open before we launch
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    _launch(tab, a, 1234)
    tab._on_windows_changed([])  # count still 1, no NEW window
    assert _state(tab, a) == LoginState.LOADING


def test_timeout_promotes_to_running(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    from tabs.launch_tab import LaunchTab
    monkeypatch.setattr(LaunchTab, "LOADING_WINDOW_TIMEOUT_MS", 60)
    wm = _FakeWM()
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    _launch(tab, a, 1234)
    assert _wait(lambda: _state(tab, a) == LoginState.RUNNING)


def test_exit_while_loading_clears_loader(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = _FakeWM()
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    launcher = _launch(tab, a, 1234)
    tab._on_game_exited("cc", a, launcher, 0)
    assert _state(tab, a) == LoginState.IDLE
    assert tab._loading["cc"] == []
    wm._counts["cc"] = 1
    tab._on_windows_changed([])
    assert _state(tab, a) == LoginState.IDLE


def test_no_window_manager_immediate_running(qapp, monkeypatch, tmp_path):
    from services.ttr_login_service import LoginState
    wm = None
    tab = _make_tab(qapp, monkeypatch, tmp_path, wm)
    (a,) = _ids(tab, 1)
    _launch(tab, a, 1234)
    assert _state(tab, a) == LoginState.RUNNING
