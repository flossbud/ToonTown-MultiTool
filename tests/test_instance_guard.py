"""One running copy per user and config directory (utils/instance_guard.py).

The claim's decisions run against a fake lock and a fake clock; the real
QLockFile and local server run across real processes further down. All of it
is a construction check: the Windows pieces (an unelevated start reaching an
elevated copy through the pipe, the foreground hand-off) need a live run.
"""

import os
import signal
import subprocess
import sys
import textwrap
import time

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from utils import instance_guard as ig
from utils import win32_elevation

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── A fake lock file and clock ─────────────────────────────────────────────

class Board:
    """The lock file as every fake process sees it."""

    def __init__(self, holder=None):
        self.holder = holder       # the pid written in the file
        self.owner = None          # the FakeLock (process) holding it, if one here
        self.dead = set()          # holders that are gone (Qt could not tell)
        self.unusable = False


class FakeLock:
    def __init__(self, board, pid):
        self.board, self.pid = board, pid

    def try_lock(self):
        held = self.board.holder is not None and self.board.owner is not self
        if self.board.unusable or held:
            return False
        self.board.holder, self.board.owner = self.pid, self
        return True

    def held_by_another(self):
        return not self.board.unusable

    def error_text(self):
        return "PermissionError"

    def holder_pid(self):
        return self.board.holder

    def remove_if_dead(self):
        if self.board.holder in self.board.dead:
            self.board.holder = self.board.owner = None
            return True
        return False

    def unlock(self):
        if self.board.owner is self:
            self.board.holder = self.board.owner = None


class Clock:
    """Fake time; `at(t, fn)` runs fn when the sleeping claim reaches t."""

    def __init__(self):
        self.t = 0.0
        self.events = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        due = [e for e in self.events if e[0] <= self.t]
        for e in due:
            self.events.remove(e)
            e[1]()

    def at(self, t, fn):
        self.events.append((t, fn))


class Asks:
    def __init__(self, answer=True):
        self.answer, self.calls = answer, []

    def __call__(self, pid):
        self.calls.append(pid)
        return self.answer


def _claim(board, pid, ask, clock, predecessor=None):
    return ig.claim(FakeLock(board, pid), ask, predecessor=predecessor,
                    clock=clock.now, sleep=clock.sleep)


# ── Ordinary starts ────────────────────────────────────────────────────────

def test_a_free_lock_makes_this_the_copy():
    ask, clock = Asks(), Clock()
    assert _claim(Board(), 10, ask, clock).state == ig.OWNER
    assert ask.calls == []


def test_a_second_start_asks_the_running_copy_and_does_not_start():
    board, ask, clock = Board(holder=10), Asks(), Clock()
    result = _claim(board, 20, ask, clock)
    assert result.state == ig.SHOWN and result.holder == 10
    assert ask.calls == [10]
    assert board.holder == 10
    assert result.line() == ("[NextUI] already running: asked the running copy "
                             "to show its window")


def test_a_copy_that_does_not_answer_still_keeps_a_second_one_out():
    board, ask, clock = Board(holder=10), Asks(answer=False), Clock()
    result = _claim(board, 20, ask, clock)
    assert result.state == ig.UNREACHABLE
    assert board.holder == 10
    assert "not starting a second copy" in result.line()
    assert "pid 10" in result.line()


def test_a_dead_holder_qt_could_not_tell_apart_does_not_block_a_start():
    # Its pid was reused by another python: Qt's own stale check says
    # "running", nobody answers, and the file lock shows it is gone.
    board, ask, clock = Board(holder=10), Asks(answer=False), Clock()
    board.dead.add(10)
    result = _claim(board, 20, ask, clock)
    assert result.state == ig.OWNER
    assert board.holder == 20


def test_an_unusable_lock_never_stops_the_app_starting():
    board, ask, clock = Board(), Asks(), Clock()
    board.unusable = True
    result = _claim(board, 20, ask, clock)
    assert result.state == ig.UNGUARDED
    assert "starting without it" in result.line()


# ── Hand-overs ─────────────────────────────────────────────────────────────

def test_the_elevated_copy_waits_for_its_predecessor_and_never_asks_it():
    board, ask, clock = Board(holder=10), Asks(), Clock()
    clock.at(1.5, lambda: setattr(board, "holder", None))     # 10 has exited
    result = _claim(board, 20, ask, clock, predecessor=10)
    assert result.state == ig.OWNER
    assert ask.calls == []
    assert clock.t < 2.0


def test_the_gap_won_by_an_ordinary_start_ends_with_that_one_copy():
    """The unelevated copy (10) let go; an ordinary start (30) took the lock
    before the elevated copy (20) did. 20 stops waiting at once and hands
    over to 30."""
    board, ask, clock = Board(holder=10), Asks(), Clock()
    clock.at(0.3, lambda: setattr(board, "holder", 30))
    result = _claim(board, 20, ask, clock, predecessor=10)
    assert result.state == ig.SHOWN and result.holder == 30
    assert ask.calls == [30]
    assert board.holder == 30
    assert clock.t < 1.0                    # not the 20 s hand-over wait


def test_the_gap_won_by_the_elevated_copy_ends_with_that_one_copy():
    board, clock = Board(holder=10), Clock()
    clock.at(0.3, lambda: setattr(board, "holder", None))
    elevated = _claim(board, 20, Asks(), clock, predecessor=10)
    ordinary_asks = Asks()
    ordinary = _claim(board, 30, ordinary_asks, clock)
    assert elevated.state == ig.OWNER
    assert ordinary.state == ig.SHOWN and ordinary_asks.calls == [20]
    assert board.holder == 20


def test_a_predecessor_that_never_exits_is_not_joined_by_a_second_copy():
    board, ask, clock = Board(holder=10), Asks(), Clock()
    result = _claim(board, 20, ask, clock, predecessor=10)
    assert result.state == ig.UNREACHABLE
    assert ask.calls == []                   # never asks an exiting copy to show
    assert clock.t >= ig.HANDOVER_WAIT_S
    assert "has not exited" in result.line()


def test_after_an_exec_this_process_takes_its_own_lock_over_at_once():
    """The restart after a source update execs in place: the lock file still
    names this pid, Qt sees it running, but the exec dropped the file lock."""
    board, ask, clock = Board(holder=20), Asks(), Clock()
    board.dead.add(20)                       # nobody holds the file lock
    result = ig.claim(FakeLock(board, 20), ask, clock=clock.now,
                      sleep=clock.sleep, own_pid=20)
    assert result.state == ig.OWNER
    assert ask.calls == []                   # no 4 s wait for an answer


def test_a_live_holder_with_this_pid_in_another_sandbox_is_still_a_copy():
    # Flatpak: each sandbox numbers its own processes, so the running copy's
    # pid in the lock file can equal this one's. Its file lock is live.
    board, ask, clock = Board(holder=2), Asks(), Clock()
    result = ig.claim(FakeLock(board, 2), ask, clock=clock.now,
                      sleep=clock.sleep, own_pid=2)
    assert result.state == ig.SHOWN
    assert board.holder == 2


def test_the_handover_arg_names_this_process():
    assert ig.handover_arg() == f"--handover-from={os.getpid()}"
    assert ig.predecessor_of([ig.handover_arg()]) == os.getpid()


def test_the_relaunch_names_this_process_as_the_predecessor():
    params = win32_elevation._relaunch_params(["--debug"], {})
    assert f"{win32_elevation.HANDOVER_FLAG}={os.getpid()}" in params
    assert ig.predecessor_of(params) == os.getpid()


def test_a_relaunch_does_not_carry_an_old_predecessor_along():
    out = win32_elevation.build_relaunch_params(
        ["--debug", f"{win32_elevation.HANDOVER_FLAG}=123"])
    assert not any(t.startswith(win32_elevation.HANDOVER_FLAG) for t in out)


@pytest.mark.parametrize("argv, expected", [
    ([], None), (["--handover-from=77"], 77), (["--handover-from=x"], None),
    (["--handover-from=0"], None), (["--handover-from"], None),
])
def test_predecessor_of(argv, expected):
    assert ig.predecessor_of(argv) == expected


# ── Startup order ──────────────────────────────────────────────────────────

class FakeGuard:
    def __init__(self, result):
        self.result, self.released, self.predecessor = result, False, "unset"

    def claim(self, predecessor=None):
        self.predecessor = predecessor
        return self.result

    def release(self):
        self.released = True


class Elevate:
    def __init__(self, state):
        self.state, self.calls = state, 0

    def __call__(self):
        self.calls += 1
        return self


@pytest.mark.parametrize("flag", sorted(win32_elevation.NO_WINDOW_FLAGS))
def test_no_window_modes_never_take_or_check_the_lock(flag):
    made = []
    elevate = Elevate(win32_elevation.SKIPPED)
    start = ig.run_startup([flag], elevate, make_guard=lambda: made.append(1))
    assert made == []
    assert start.guard is None and start.exit_code is None
    assert elevate.calls == 1


def test_a_second_start_exits_before_any_administrator_prompt():
    lines = []
    guard = FakeGuard(ig.Claim(ig.SHOWN, 10))
    elevate = Elevate(win32_elevation.PROMPT)
    start = ig.run_startup([], elevate, make_guard=lambda: guard, out=lines.append)
    assert start.exit_code == 0
    assert elevate.calls == 0
    assert lines == ["[NextUI] already running: asked the running copy to show its window"]


def test_the_relaunched_process_lets_go_for_its_elevated_copy():
    guard = FakeGuard(ig.Claim(ig.OWNER))
    start = ig.run_startup([], Elevate(win32_elevation.RELAUNCHED),
                           make_guard=lambda: guard)
    assert start.exit_code == 0
    assert guard.released is True


@pytest.mark.parametrize("state", [win32_elevation.DECLINED, win32_elevation.SKIPPED,
                                   win32_elevation.ELEVATED])
def test_a_declined_or_skipped_prompt_keeps_the_lock(state):
    guard = FakeGuard(ig.Claim(ig.OWNER))
    start = ig.run_startup([], Elevate(state), make_guard=lambda: guard)
    assert start.exit_code is None
    assert start.guard is guard
    assert guard.released is False


def test_the_handover_pid_reaches_the_claim():
    guard = FakeGuard(ig.Claim(ig.OWNER))
    ig.run_startup(["--elevation-restart=uipi", "--handover-from=4242"],
                   Elevate(win32_elevation.ELEVATED), make_guard=lambda: guard)
    assert guard.predecessor == 4242


# ── Names ──────────────────────────────────────────────────────────────────

def test_the_name_is_keyed_by_user_and_resolved_config_dir(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (tmp_path / "link").symlink_to(a)
    env = {}
    name = lambda d, u="me": ig.server_name(str(d), u, platform="linux", environ=env)
    assert name(a) == name(str(a) + os.sep) == name(tmp_path / "link")
    assert name(a) != name(b)
    assert name(a) != name(a, "someone-else")


def test_the_name_on_each_platform(tmp_path):
    runtime = tmp_path / "run"
    (runtime / "app" / "io.example.App").mkdir(parents=True)
    cfg = str(tmp_path)
    win = ig.server_name(cfg, "me", platform="win32", environ={})
    assert win.startswith("ttmt-") and os.sep not in win
    plain = ig.server_name(cfg, "me", platform="linux",
                           environ={"XDG_RUNTIME_DIR": str(runtime)})
    assert plain == str(runtime / win) + ".sock"
    flatpak = ig.server_name(cfg, "me", platform="linux",
                             environ={"XDG_RUNTIME_DIR": str(runtime),
                                      "FLATPAK_ID": "io.example.App"})
    assert flatpak == str(runtime / "app" / "io.example.App" / win) + ".sock"
    mac = ig.server_name(cfg, "me", platform="darwin", environ={})
    assert mac == win


# ── Windows foreground ─────────────────────────────────────────────────────

class _User32:
    def __init__(self):
        self.calls = []

        def asfw(pid):
            self.calls.append(pid)
            return 1
        self.AllowSetForegroundWindow = asfw


def test_the_running_copy_is_allowed_the_foreground_before_it_is_asked(monkeypatch):
    import ctypes
    user32 = _User32()
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": user32}),
                        raising=False)
    assert ig.allow_foreground(4242, platform="win32") is True
    assert ig.allow_foreground(None, platform="win32") is True
    assert user32.calls == [4242, 0xFFFFFFFF]            # ASFW_ANY without a pid
    assert ig.allow_foreground(4242, platform="linux") is False


def test_asking_allows_the_foreground_first(monkeypatch):
    order = []
    monkeypatch.setattr(ig, "allow_foreground", lambda pid: order.append(("allow", pid)))
    clock = Clock()
    ig.ask_to_show("ttmt-nobody-listens", 77, connect_wait_s=0.0,
                   clock=clock.now, sleep=clock.sleep)
    assert order == [("allow", 77)]


# ── Real processes (Linux here; construction checks) ───────────────────────

_FIRST_COPY = textwrap.dedent("""
    import sys
    sys.path.insert(0, {repo!r})
    from PySide6.QtCore import QCoreApplication, QTimer
    from utils.instance_guard import InstanceGuard
    app = QCoreApplication([])
    guard = InstanceGuard({cfg!r})
    result = guard.claim()
    print("claim", result.state, flush=True)
    if result.state != "owner":
        sys.exit(3)
    guard.listen()
    guard.on_show(lambda: (print("SHOWN", flush=True), app.quit()))
    print("ready", flush=True)
    QTimer.singleShot({linger_ms}, app.quit)
    app.exec()
    guard.release()
""")


def _start_first_copy(cfg, linger_ms=20000):
    proc = subprocess.Popen(
        [sys.executable, "-c", _FIRST_COPY.format(repo=REPO, cfg=str(cfg),
                                                  linger_ms=linger_ms)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 30
    seen = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        seen.append(line)
        if line.strip() == "ready":
            return proc
        if not line and proc.poll() is not None:
            break
    proc.kill()
    raise AssertionError(f"first copy did not start: {seen}")


def test_a_second_start_reaches_the_running_copy(tmp_path):
    first = _start_first_copy(tmp_path)
    try:
        result = ig.InstanceGuard(str(tmp_path)).claim()
        assert result.state == ig.SHOWN
        assert result.holder == first.pid
        out, _ = first.communicate(timeout=30)
        assert "SHOWN" in out
        assert "another start asked this copy to show its window" in out
    finally:
        if first.poll() is None:
            first.kill()


def test_another_config_dir_is_another_copy(tmp_path):
    (tmp_path / "a").mkdir()
    first = _start_first_copy(tmp_path / "a")
    try:
        guard = ig.InstanceGuard(str(tmp_path / "b"))
        assert guard.claim().state == ig.OWNER
        guard.release()
    finally:
        first.kill()
        first.wait()


def test_a_crashed_copy_does_not_block_the_next_start(tmp_path):
    first = _start_first_copy(tmp_path)
    first.send_signal(signal.SIGKILL)
    first.wait()
    assert os.path.exists(tmp_path / ig.LOCK_FILE)          # left behind
    guard = ig.InstanceGuard(str(tmp_path))
    try:
        assert guard.claim().state == ig.OWNER
    finally:
        guard.release()


def test_a_request_before_the_window_exists_is_carried_out_once_it_does(qapp, tmp_path):
    guard = ig.InstanceGuard(str(tmp_path))
    assert guard.claim().state == ig.OWNER
    try:
        assert guard.listen() is True
        asker = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {REPO!r}); "
             "from utils.instance_guard import ask_to_show; "
             f"print(ask_to_show({guard.name!r}))"],
            stdout=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 30
        while asker.poll() is None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert asker.stdout.read().strip() == "True"
        shown = []
        guard.on_show(lambda: shown.append(1))
        assert shown == [1]
        guard.on_show(lambda: shown.append(2))               # carried out once
        assert shown == [1]
    finally:
        guard.release()


def test_release_lets_the_next_start_be_the_copy(tmp_path):
    first = ig.InstanceGuard(str(tmp_path))
    assert first.claim().state == ig.OWNER
    first.release()
    second = ig.InstanceGuard(str(tmp_path))
    try:
        assert second.claim().state == ig.OWNER
    finally:
        second.release()
