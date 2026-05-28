import os
import subprocess

from utils import host_spawn


def test_host_popen_forwards_copied_xauthority_when_requested(monkeypatch):
    captured = {}

    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    monkeypatch.setattr(
        host_spawn,
        "host_visible_xauthority",
        lambda: "/home/test/.cache/ttmt-host/Xauthority",
    )

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    host_spawn.host_popen(
        ["TTREngine"],
        env={"DISPLAY": ":0", "XAUTHORITY": "/run/flatpak/Xauthority"},
        forward_xauthority=True,
    )

    assert "--env=XAUTHORITY=/home/test/.cache/ttmt-host/Xauthority" in captured["argv"]
    assert "--env=XAUTHORITY=/run/flatpak/Xauthority" not in captured["argv"]
    assert "--env=DISPLAY=:0" in captured["argv"]


def test_host_popen_strips_sandbox_xauthority_by_default(monkeypatch):
    captured = {}

    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    host_spawn.host_popen(
        ["env"],
        env={"DISPLAY": ":0", "XAUTHORITY": "/run/flatpak/Xauthority"},
    )

    assert "--env=XAUTHORITY=/run/flatpak/Xauthority" not in captured["argv"]
    assert "--env=DISPLAY=:0" in captured["argv"]


def test_host_visible_cache_dir_uses_xdg_when_valid(tmp_path, monkeypatch):
    cache_home = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))

    path = host_spawn.host_visible_cache_dir("launch-logs")

    assert path == str(cache_home / "launch-logs")
    assert os.path.isdir(path)
    assert (os.stat(path).st_mode & 0o777) == 0o700


def test_host_visible_cache_dir_falls_back_to_flatpak_app_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("FLATPAK_ID", "io.example.App")
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)

    path = host_spawn.host_visible_cache_dir("host-spawn")

    assert path == str(
        tmp_path / ".var" / "app" / "io.example.App" / "cache" / "host-spawn"
    )
    assert os.path.isdir(path)
    assert (os.stat(path).st_mode & 0o777) == 0o700


def test_host_visible_cache_dir_rejects_sandbox_xdg(tmp_path, monkeypatch):
    # A sandbox-internal XDG_CACHE_HOME must be rejected in favour of a
    # host-visible path; host-spawned processes can't resolve /run/flatpak/*.
    monkeypatch.setenv("XDG_CACHE_HOME", "/run/flatpak/cache")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: False)

    path = host_spawn.host_visible_cache_dir("launch-logs")

    assert path == str(tmp_path / ".cache" / "launch-logs")
    assert os.path.isdir(path)


def test_host_visible_xauthority_copies_sandbox_cookie(tmp_path, monkeypatch):
    src = tmp_path / "src-Xauthority"
    src.write_bytes(b"\x01\x02cookie-bytes")
    monkeypatch.setenv("XAUTHORITY", str(src))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("FLATPAK_ID", "io.example.App")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)

    dest = host_spawn.host_visible_xauthority()

    assert dest is not None
    assert dest != str(src)
    assert os.path.isfile(dest)
    with open(dest, "rb") as fh:
        assert fh.read() == b"\x01\x02cookie-bytes"
    assert (os.stat(dest).st_mode & 0o777) == 0o600


def test_host_visible_xauthority_returns_none_for_empty_cookie(tmp_path, monkeypatch):
    src = tmp_path / "empty-Xauthority"
    src.write_bytes(b"")
    monkeypatch.setenv("XAUTHORITY", str(src))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)

    assert host_spawn.host_visible_xauthority() is None


def test_host_visible_xauthority_passthrough_when_not_sandboxed(tmp_path, monkeypatch):
    src = tmp_path / "host-Xauthority"
    src.write_bytes(b"real-host-cookie")
    monkeypatch.setenv("XAUTHORITY", str(src))
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: False)

    assert host_spawn.host_visible_xauthority() == str(src)


def test_host_visible_xauthority_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("XAUTHORITY", raising=False)

    assert host_spawn.host_visible_xauthority() is None
