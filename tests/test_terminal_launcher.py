import shutil
import subprocess

import pytest

from utils.terminal_launcher import (
    detect_terminal,
    build_argv,
    run_in_terminal,
    TERMINAL_ORDER,
)


def test_detect_terminal_respects_env(monkeypatch):
    monkeypatch.setenv("TERMINAL", "/usr/bin/my-term")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/my-term" if name == "/usr/bin/my-term" else None)
    assert detect_terminal() == "/usr/bin/my-term"


def test_detect_terminal_probes_known_terminals(monkeypatch):
    monkeypatch.delenv("TERMINAL", raising=False)
    available = {"konsole": "/usr/bin/konsole"}
    monkeypatch.setattr(shutil, "which", lambda name: available.get(name))
    assert detect_terminal() == "/usr/bin/konsole"


def test_detect_terminal_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert detect_terminal() is None


def test_detect_terminal_picks_first_in_order(monkeypatch):
    monkeypatch.delenv("TERMINAL", raising=False)
    available = {"gnome-terminal": "/usr/bin/gnome-terminal", "xterm": "/usr/bin/xterm"}
    monkeypatch.setattr(shutil, "which", lambda name: available.get(name))
    # gnome-terminal comes before xterm in TERMINAL_ORDER
    assert detect_terminal() == "/usr/bin/gnome-terminal"


@pytest.mark.parametrize("terminal,cmd,expected_tail", [
    ("/usr/bin/gnome-terminal", ["echo", "hi"], ["--", "echo", "hi"]),
    ("/usr/bin/konsole", ["echo", "hi"], ["-e", "echo", "hi"]),
    ("/usr/bin/xterm", ["echo", "hi"], ["-e", "echo", "hi"]),
    ("/usr/bin/xfce4-terminal", ["echo", "hi"], ["--command", "echo hi"]),
    ("/usr/bin/kitty", ["echo", "hi"], ["echo", "hi"]),
    ("/usr/bin/alacritty", ["echo", "hi"], ["-e", "echo", "hi"]),
])
def test_build_argv_per_terminal(terminal, cmd, expected_tail):
    argv = build_argv(terminal, cmd)
    assert argv[0] == terminal
    assert argv[1:] == expected_tail


def test_build_argv_xfce_shell_quotes_spaces():
    # xfce4-terminal passes --command to a shell. Paths with spaces
    # must round-trip through shell parsing without losing the boundary.
    argv = build_argv("/usr/bin/xfce4-terminal", ["pkexec", "apt", "install", "/tmp/foo bar.deb"])
    assert argv[0] == "/usr/bin/xfce4-terminal"
    assert argv[1] == "--command"
    assert argv[2] == "pkexec apt install '/tmp/foo bar.deb'"


def test_run_in_terminal_returns_false_when_no_terminal(monkeypatch):
    monkeypatch.setattr("utils.terminal_launcher.detect_terminal", lambda: None)
    assert run_in_terminal(["echo", "hi"], lambda rc: None) is False


def test_run_in_terminal_returns_false_on_popen_error(monkeypatch):
    monkeypatch.setattr("utils.terminal_launcher.detect_terminal", lambda: "/usr/bin/xterm")

    def boom(*a, **kw):
        raise OSError("not found")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert run_in_terminal(["echo", "hi"], lambda rc: None) is False


def test_detect_terminal_uses_host_path_in_flatpak(monkeypatch):
    # Inside a Flatpak sandbox the host's terminals are not on the sandbox
    # PATH, so shutil.which finds nothing. Detection must probe the host via
    # flatpak-spawn (host_check_output) instead.
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    def fake_host_check_output(argv, **kwargs):
        name = argv[-1]
        # `which` emits a trailing newline; detection must strip it.
        table = {"konsole": b"/usr/bin/konsole\n", "kitty": b"/usr/bin/kitty\n"}
        if name in table:
            return table[name]
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr("utils.host_spawn.host_check_output", fake_host_check_output)
    # gnome-terminal is absent on the host; konsole is present and precedes
    # kitty in TERMINAL_ORDER, so konsole wins with no trailing newline.
    assert detect_terminal() == "/usr/bin/konsole"


def test_run_in_terminal_host_launches_in_flatpak(monkeypatch):
    # Inside Flatpak the terminal is a host GUI process: it must be launched on
    # the host (host_popen with X11 auth forwarded), the payload kept raw, and
    # the sandbox-local subprocess.Popen must NOT be used.
    monkeypatch.setattr("utils.terminal_launcher.detect_terminal", lambda: "/usr/bin/konsole")
    monkeypatch.setattr("utils.host_spawn.in_flatpak", lambda: True)

    captured = {}

    class _FakeProc:
        def wait(self):
            return 0

    def fake_host_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr("utils.host_spawn.host_popen", fake_host_popen)

    def _no_popen(*a, **k):
        raise AssertionError("sandbox subprocess.Popen used in Flatpak path")

    monkeypatch.setattr(subprocess, "Popen", _no_popen)

    assert run_in_terminal(["flatpak", "update", "-y", "x"], lambda rc: None) is True
    assert captured["argv"] == ["/usr/bin/konsole", "-e", "flatpak", "update", "-y", "x"]
    assert "flatpak-spawn" not in captured["argv"]
    assert captured["kwargs"].get("forward_xauthority") is True
    # forward_xauthority is a no-op unless an env is actually passed.
    assert captured["kwargs"].get("env") is not None


def test_terminal_order_and_build_argv_are_consistent():
    # Every name in TERMINAL_ORDER must have an explicit branch in build_argv
    # (or intentionally fall through to the -e fallback). Drift here would
    # silently route a detected terminal through the wrong argv shape.
    handled = {
        "gnome-terminal", "konsole", "xfce4-terminal",
        "kitty", "alacritty", "xterm",
    }
    assert set(TERMINAL_ORDER) == handled
