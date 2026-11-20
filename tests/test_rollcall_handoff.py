"""The app's side of the update handoff: start Setup in update mode, return
True only once the update window says it is up."""
import os
import subprocess
import sys

from utils.rollcall import handoff
from utils.rollcall import protocol as P

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Proc:
    def __init__(self, code=None):
        self.returncode = code

    def poll(self):
        return self.returncode


def _ready_path(command):
    marker = "/RCREADY="
    start = command.index(marker) + len(marker)
    return command[start:].split(" ")[0].strip('"')


def _run(tmp_path, react, **kwargs):
    setup = tmp_path / "Setup.exe"
    setup.write_bytes(b"MZ")
    seen = {}

    def popen(command):
        seen["command"] = command
        return react(command)

    logs = []
    ok = handoff.start_update_window(str(setup), app_pid=4242, from_version="v0.8.0-alpha.1",
                                     popen=popen, sleep=lambda s: None, log=logs.append,
                                     **kwargs)
    return ok, seen.get("command", ""), logs


def test_true_once_the_window_is_up(tmp_path):
    def react(command):
        P.write_ready(_ready_path(command), P.READY_UP)
        return Proc()

    ok, command, _ = _run(tmp_path, react)
    assert ok
    assert "/RCMODE=update" in command and "/RCPID=4242" in command
    assert "/RCFROM=v0.8.0-alpha.1" in command
    assert not os.path.exists(_ready_path(command))     # cleaned up


def test_false_when_setup_has_no_window(tmp_path):
    def react(command):
        P.write_ready(_ready_path(command), P.READY_NO_WINDOW)
        return Proc(3)

    assert _run(tmp_path, react)[0] is False


def test_false_when_setup_exits_without_a_word(tmp_path):
    assert _run(tmp_path, lambda command: Proc(1))[0] is False


def test_false_after_the_timeout(tmp_path):
    ticks = iter(range(1000))
    ok, _, logs = _run(tmp_path, lambda command: Proc(), clock=lambda: next(ticks),
                       timeout_s=5)
    assert ok is False and any("in time" in line for line in logs)


def test_false_without_an_installer(tmp_path):
    assert handoff.start_update_window(str(tmp_path / "missing.exe"), app_pid=1,
                                       from_version="v1", log=lambda s: None) is False


def test_setup_is_started_outside_the_app_folder(tmp_path, monkeypatch):
    # The app runs in its install folder; Setup inheriting that folder would
    # keep the update from moving the install aside.
    app_dir = tmp_path / "Programs" / "ToonTown MultiTool"
    app_dir.mkdir(parents=True)
    windows = tmp_path / "Windows"
    (windows / "System32").mkdir(parents=True)
    monkeypatch.chdir(app_dir)
    monkeypatch.setenv("SystemRoot", str(windows))
    seen = {}

    def fake_popen(command, **kwargs):
        seen.update(kwargs)
        return Proc(0)

    monkeypatch.setattr(handoff.subprocess, "Popen", fake_popen)
    handoff._popen("Setup.exe /RCMODE=update")
    assert seen["cwd"] == str(windows / "System32")

    monkeypatch.delenv("SystemRoot")
    monkeypatch.delenv("windir", raising=False)
    handoff._popen("Setup.exe /RCMODE=update")
    assert seen["cwd"] == handoff.tempfile.gettempdir()
    assert not seen["cwd"].startswith(str(app_dir))


def test_importing_it_pulls_in_nothing_heavy():
    code = ("import sys; import utils.rollcall.handoff; "
            "heavy = [m for m in sys.modules if m.split('.')[0] in "
            "('PySide6', 'shiboken6', 'requests', 'pynput', 'keyring')]; "
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == ""
