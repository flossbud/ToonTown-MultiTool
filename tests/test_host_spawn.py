import os
import subprocess

import pytest

from utils import host_spawn


def test_env_block_memfd_serializes_nul_separated():
    fd = host_spawn._env_block_memfd({"A": "1", "B": "two"})
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 4096)
    finally:
        os.close(fd)
    # env -0 format: NUL-terminated KEY=VALUE records, insertion order.
    assert raw == b"A=1\x00B=two\x00"


def _spawn_capture(monkeypatch):
    """Install a fake subprocess.Popen that records argv/kwargs and, when an
    --env-fd flag is present, reads the in-memory env block back (the fd is
    still open during the Popen call). Returns the dict it populates."""
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        block = {}
        for arg in argv:
            if isinstance(arg, str) and arg.startswith("--env-fd="):
                fd = int(arg.split("=", 1)[1])
                os.lseek(fd, 0, os.SEEK_SET)
                raw = b""
                while True:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    raw += chunk
                for record in raw.split(b"\0"):
                    if record:
                        k, _, v = record.partition(b"=")
                        block[k.decode()] = v.decode()
        captured["env_fd_block"] = block
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return captured


def test_host_popen_routes_env_through_env_fd_not_argv(monkeypatch):
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    captured = _spawn_capture(monkeypatch)

    host_spawn.host_popen(
        ["TTREngine"],
        env={"DISPLAY": ":0", "TTR_PLAYCOOKIE": "secret-cookie"},
    )

    argv = captured["argv"]
    assert not any(isinstance(a, str) and a.startswith("--env=") for a in argv)
    assert all("secret-cookie" not in str(a) for a in argv)
    env_fd_flags = [a for a in argv if isinstance(a, str) and a.startswith("--env-fd=")]
    assert len(env_fd_flags) == 1
    fd = int(env_fd_flags[0].split("=", 1)[1])
    assert fd in captured["kwargs"]["pass_fds"]
    assert captured["env_fd_block"]["TTR_PLAYCOOKIE"] == "secret-cookie"
    assert captured["env_fd_block"]["DISPLAY"] == ":0"


def test_host_popen_no_env_means_no_env_fd(monkeypatch):
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    captured = _spawn_capture(monkeypatch)

    host_spawn.host_popen(["xdg-open", "https://example.test"])

    argv = captured["argv"]
    assert not any(isinstance(a, str) and a.startswith("--env-fd=") for a in argv)
    assert not captured["kwargs"].get("pass_fds")


def test_host_popen_closes_env_fd_after_spawn(monkeypatch):
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    seen = {}

    def fake_popen(argv, **kwargs):
        for a in argv:
            if isinstance(a, str) and a.startswith("--env-fd="):
                seen["fd"] = int(a.split("=", 1)[1])
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    host_spawn.host_popen(["TTREngine"], env={"TTR_PLAYCOOKIE": "secret"})

    assert "fd" in seen
    with pytest.raises(OSError):
        os.fstat(seen["fd"])  # parent must close its copy after the spawn


def test_host_popen_forwards_copied_xauthority_when_requested(monkeypatch):
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    monkeypatch.setattr(
        host_spawn, "host_visible_xauthority",
        lambda: "/home/test/.cache/ttmt-host/Xauthority",
    )
    captured = _spawn_capture(monkeypatch)

    host_spawn.host_popen(
        ["TTREngine"],
        env={"DISPLAY": ":0", "XAUTHORITY": "/run/flatpak/Xauthority"},
        forward_xauthority=True,
    )

    argv = captured["argv"]
    assert not any(isinstance(a, str) and a.startswith("--env=") for a in argv)
    assert all("/run/flatpak/Xauthority" not in str(a) for a in argv)
    assert captured["env_fd_block"]["XAUTHORITY"] == "/home/test/.cache/ttmt-host/Xauthority"
    assert captured["env_fd_block"]["DISPLAY"] == ":0"


def test_host_popen_strips_sandbox_xauthority_by_default(monkeypatch):
    monkeypatch.setattr(host_spawn, "in_flatpak", lambda: True)
    monkeypatch.setattr(host_spawn.shutil, "which", lambda name: "/usr/bin/flatpak-spawn")
    captured = _spawn_capture(monkeypatch)

    host_spawn.host_popen(
        ["env"],
        env={"DISPLAY": ":0", "XAUTHORITY": "/run/flatpak/Xauthority"},
    )

    # Without forward_xauthority the sandbox cookie is dropped entirely; only
    # the host-safe var survives, and it travels via the fd, not argv.
    assert captured["env_fd_block"] == {"DISPLAY": ":0"}
    assert not any(isinstance(a, str) and a.startswith("--env=") for a in captured["argv"])


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


def test_build_forwarded_env_filters_sandbox_vars_and_paths():
    result = host_spawn._build_forwarded_env(
        {
            "DISPLAY": ":0",
            "TTR_PLAYCOOKIE": "secret",
            "PATH": "/app/bin",                       # sandbox-only KEY -> dropped
            "XAUTHORITY": "/run/flatpak/Xauthority",  # sandbox-only + sandbox path -> dropped
            "RESBASE": "/app/lib/x",                  # sandbox path VALUE -> dropped
            "EMPTY": None,                            # None -> dropped
        },
        forward_xauthority=False,
    )
    assert result == {"DISPLAY": ":0", "TTR_PLAYCOOKIE": "secret"}


def test_build_forwarded_env_none_returns_empty():
    assert host_spawn._build_forwarded_env(None, forward_xauthority=False) == {}


def test_build_forwarded_env_forward_xauthority_drops_xauth_when_host_copy_unavailable(monkeypatch):
    monkeypatch.setattr(host_spawn, "host_visible_xauthority", lambda: None)
    result = host_spawn._build_forwarded_env(
        {"XAUTHORITY": "/run/flatpak/Xauthority", "DISPLAY": ":0"},
        forward_xauthority=True,
    )
    assert "XAUTHORITY" not in result
    assert result == {"DISPLAY": ":0"}


def test_build_forwarded_env_forward_xauthority_uses_host_copy(monkeypatch):
    monkeypatch.setattr(
        host_spawn, "host_visible_xauthority",
        lambda: "/home/test/cache/Xauthority",
    )
    result = host_spawn._build_forwarded_env(
        {"XAUTHORITY": "/run/flatpak/Xauthority", "DISPLAY": ":0"},
        forward_xauthority=True,
    )
    assert result["XAUTHORITY"] == "/home/test/cache/Xauthority"
    assert result["DISPLAY"] == ":0"
