"""Tests for TTRLauncher process dispatch."""

import os
import threading
import tempfile
import time

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from services import ttr_launcher


def _qapp():
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _fd_is_closed(fd):
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


class _Proc:
    pid = 4242

    def __init__(self, returncode=0):
        self._returncode = returncode

    def wait(self):
        return self._returncode


def test_flatpak_ttr_engine_uses_direct_host_launch_with_xauthority(tmp_path, monkeypatch):
    """Launch the selected TTREngine directly on the host and ask host_popen to
    forward a host-visible Xauthority file so X11 auth survives the flatpak-spawn
    boundary. The Xauthority copy/injection itself is host_popen's responsibility
    (covered in test_host_spawn.py); here we only assert the launcher requests it
    via forward_xauthority and does not embed the cookie in argv."""
    _qapp()
    engine_dir = tmp_path / "ttr-data"
    engine_dir.mkdir()
    engine = engine_dir / "TTREngine"
    engine.write_bytes(b"")
    os.chmod(engine, 0o755)

    captured = {}
    spawned = threading.Event()

    monkeypatch.setattr(ttr_launcher, "_is_trusted_engine_path", lambda *_: True)

    def fake_host_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        spawned.set()
        return _Proc()

    monkeypatch.setattr(ttr_launcher, "host_popen", fake_host_popen)

    launcher = ttr_launcher.TTRLauncher()
    launcher.launch("gameserver", "secret-cookie", str(engine_dir))

    assert spawned.wait(timeout=2.0), "TTR launcher did not spawn"
    assert captured["cmd"] == [str(engine)]
    assert "secret-cookie" not in " ".join(captured["cmd"])
    assert captured["kwargs"]["env"]["TTR_PLAYCOOKIE"] == "secret-cookie"
    assert captured["kwargs"]["env"]["TTR_GAMESERVER"] == "gameserver"
    assert captured["kwargs"]["forward_xauthority"] is True
    assert captured["kwargs"]["cwd"] == str(engine_dir)


def test_ttr_nonzero_exit_emits_captured_log_tail(tmp_path, monkeypatch):
    """TTR failures should carry stderr/stdout diagnostics like CC failures."""
    _qapp()
    engine_dir = tmp_path / "native-ttr"
    engine_dir.mkdir()
    engine = engine_dir / "TTREngine"
    engine.write_bytes(b"")
    os.chmod(engine, 0o755)

    exited = threading.Event()
    observed = {}

    monkeypatch.setattr(ttr_launcher, "in_flatpak", lambda: False, raising=False)
    monkeypatch.setattr(ttr_launcher, "_is_trusted_engine_path", lambda *_: True)

    def fake_host_popen(_cmd, **kwargs):
        kwargs["stdout"].write(b"stdout detail\n")
        kwargs["stderr"].write(b"stderr detail\n")
        return _Proc(returncode=7)

    monkeypatch.setattr(ttr_launcher, "host_popen", fake_host_popen)

    launcher = ttr_launcher.TTRLauncher()

    def on_exit(retcode, raw_log):
        observed["retcode"] = retcode
        observed["raw_log"] = raw_log
        exited.set()

    launcher.game_exited.connect(on_exit, Qt.DirectConnection)
    launcher.launch("gameserver", "cookie", str(engine_dir))

    assert exited.wait(timeout=2.0), "game_exited never fired"
    assert observed["retcode"] == 7
    assert "stderr detail" in observed["raw_log"]
    assert "stdout detail" in observed["raw_log"]


def test_ttr_clean_exit_unlinks_capture_files(tmp_path, monkeypatch):
    """Successful launches should not accumulate ttmt-ttr temp logs."""
    _qapp()
    engine_dir = tmp_path / "native-ttr"
    engine_dir.mkdir()
    engine = engine_dir / "TTREngine"
    engine.write_bytes(b"")
    os.chmod(engine, 0o755)

    exited = threading.Event()
    paths = []

    monkeypatch.setattr(ttr_launcher, "in_flatpak", lambda: False, raising=False)
    monkeypatch.setattr(ttr_launcher, "_is_trusted_engine_path", lambda *_: True)
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(prefix, suffix):
        fd, path = real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)
        paths.append(path)
        return fd, path

    def fake_host_popen(_cmd, **kwargs):
        kwargs["stdout"].write(b"stdout detail\n")
        kwargs["stderr"].write(b"stderr detail\n")
        return _Proc(returncode=0)

    monkeypatch.setattr(ttr_launcher.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(ttr_launcher, "host_popen", fake_host_popen)

    launcher = ttr_launcher.TTRLauncher()
    launcher.game_exited.connect(lambda *_: exited.set(), Qt.DirectConnection)
    launcher.launch("gameserver", "cookie", str(engine_dir))

    assert exited.wait(timeout=2.0), "game_exited never fired"
    assert len(paths) == 2
    assert _wait_until(lambda: all(not os.path.exists(path) for path in paths))


def test_ttr_temp_setup_failure_closes_raw_fd(tmp_path, monkeypatch):
    """If fdopen fails during capture setup, the raw mkstemp fd is closed."""
    _qapp()
    engine_dir = tmp_path / "native-ttr"
    engine_dir.mkdir()
    engine = engine_dir / "TTREngine"
    engine.write_bytes(b"")
    os.chmod(engine, 0o755)

    failed = threading.Event()
    opened_fds = []

    monkeypatch.setattr(ttr_launcher, "in_flatpak", lambda: False, raising=False)
    monkeypatch.setattr(ttr_launcher, "_is_trusted_engine_path", lambda *_: True)
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(prefix, suffix):
        fd, path = real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)
        opened_fds.append(fd)
        return fd, path

    def fake_fdopen(_fd, _mode):
        raise OSError("fdopen failed")

    monkeypatch.setattr(ttr_launcher.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(ttr_launcher.os, "fdopen", fake_fdopen)

    launcher = ttr_launcher.TTRLauncher()
    launcher.launch_failed.connect(lambda _msg: failed.set(), Qt.DirectConnection)
    launcher.launch("gameserver", "cookie", str(engine_dir))

    assert failed.wait(timeout=2.0), "launch_failed never fired"
    assert len(opened_fds) == 2
    assert _wait_until(
        lambda: all(_fd_is_closed(fd) for fd in opened_fds)
    )
    for fd in opened_fds:
        with pytest.raises(OSError):
            os.write(fd, b"x")
