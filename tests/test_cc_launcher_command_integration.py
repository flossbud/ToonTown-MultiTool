"""Tests for cc_launcher.launch's command construction.

We don't actually spawn a process — we stub host_popen and inspect the
arguments it was called with.
"""

import sys
import pytest
from PySide6.QtCore import QCoreApplication

from services.wine_runtimes import WineInstall
from services import cc_launcher as ccl


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


def _install(launcher, tmp_path, prefix=None):
    if launcher == "native":
        exe = tmp_path / "Corporate Clash" / "CorporateClash.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        return WineInstall(str(exe), "native", None, "x", {})
    pfx = tmp_path / (prefix or "prefix")
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    md = {}
    if launcher == "bottles":
        md = {"bottle_name": "MyBottle", "distribution": "native"}
        (pfx / "bottle.yml").write_text("Name: X\n")
    return WineInstall(str(exe), launcher, str(pfx), "x", md)


def test_launch_calls_host_popen_with_built_command(qapp, tmp_path, monkeypatch):
    install = _install("wine", tmp_path)
    captured = {}

    class _Proc:
        def __init__(self): self.pid = 9999
        def poll(self): return None
        def wait(self): return 0
    monkeypatch.setattr(ccl, "host_popen",
                        lambda cmd, **kw: (captured.update(cmd=cmd, kw=kw) or _Proc()))
    # Ensure wine is "available" without touching $PATH
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: True)
    launcher = ccl.CCLauncher(settings_manager=None)
    launcher.launch("srv", "tok", install, username="bob")
    # launch runs the popen on a background thread; busy-wait for it
    import time
    for _ in range(50):
        if "cmd" in captured:
            break
        time.sleep(0.05)
    # New launcher protocol: credentials via env, not via -g/CC_OSST_TOKEN.
    assert captured.get("cmd") == ["wine", install.exe_path]
    env = captured["kw"]["env"]
    assert env["WINEPREFIX"] == install.prefix_path
    assert env["TT_PLAYCOOKIE"] == "tok"
    assert env["TT_GAMESERVER"] == "srv"
    assert env["LAUNCHER_USER"] == "bob"
    assert env["REALM"] == "production"
    assert env["SENTRY_ENVIRONMENT"] == "corporateclash"
    # CC_OSST_TOKEN is the old contract and must not leak through.
    assert "CC_OSST_TOKEN" not in env


def test_launch_fails_when_launcher_unavailable(qapp, tmp_path, monkeypatch):
    install = _install("bottles", tmp_path)
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: False)
    errors = []
    launcher = ccl.CCLauncher(settings_manager=None)
    launcher.launch_failed.connect(errors.append)
    launcher.launch("srv", "tok", install)
    qapp.processEvents()
    assert any("bottles" in e.lower() or "Bottles" in e for e in errors)


def test_steam_proton_verb_switches_to_run_for_second_launch(tmp_path):
    """Multi-instance: second launch against the same compatdata must use the
    'run' verb instead of 'waitforexitandrun' so it doesn't block on the
    existing wineserver's prefix flock."""
    from services.wine_runtimes import (
        WineInstall, build_launch_command,
        register_active_proton_compatdata,
        unregister_active_proton_compatdata,
        is_proton_compatdata_active,
    )

    # Build a fake steam-proton WineInstall pointing at tmp_path.
    steam_root = tmp_path / "steam"
    compatdata = steam_root / "steamapps" / "compatdata" / "12345"
    prefix = compatdata / "pfx"
    prefix.mkdir(parents=True)
    proton_dir = steam_root / "compatibilitytools.d" / "fake-proton"
    (proton_dir / "files" / "bin").mkdir(parents=True)
    (proton_dir / "proton").write_text("#!/bin/sh\nexit 0\n")
    (proton_dir / "files" / "bin" / "wineserver").write_text("#!/bin/sh\nexit 0\n")
    install = WineInstall(
        exe_path=str(prefix / "drive_c" / "CorporateClash.exe"),
        launcher="steam-proton",
        prefix_path=str(prefix),
        display_name="Steam · CC",
        metadata={
            "appid": "12345",
            "steam_root": str(steam_root),
            "proton_dir": str(proton_dir),
        },
    )

    # First launch: nothing registered, verb should be waitforexitandrun.
    assert not is_proton_compatdata_active(str(compatdata))
    cmd, _ = build_launch_command(install, args=[], extra_env={})
    cmd_str = " ".join(cmd)
    assert "waitforexitandrun" in cmd_str
    assert " run " not in cmd_str

    # Register this compatdata as live; second launch should switch to run.
    register_active_proton_compatdata(str(compatdata))
    try:
        cmd2, _ = build_launch_command(install, args=[], extra_env={})
        cmd2_str = " ".join(cmd2)
        assert "waitforexitandrun" not in cmd2_str or "--verb=run" in cmd2_str
        # Either the proton verb arg is "run" or the runtime wrapper's --verb is run
        assert any(part == "run" or part == "--verb=run" for part in cmd2)
    finally:
        unregister_active_proton_compatdata(str(compatdata))

    # After unregister, third launch reverts to waitforexitandrun.
    assert not is_proton_compatdata_active(str(compatdata))
    cmd3, _ = build_launch_command(install, args=[], extra_env={})
    assert "waitforexitandrun" in " ".join(cmd3)


def test_launch_sweeps_bridge_for_prefix_before_spawning_proton(tmp_path, monkeypatch):
    """Regression guard: before spawning Proton, CCLauncher must call
    wine_input_bridge.shutdown_for_prefix so any stale bridge (from a
    crashed prior TTMT session, or a CC the user closed without
    closing TTMT) is torn down. Otherwise Proton's waitforexitandrun
    blocks in fcntl_setlk waiting for the prefix lock."""
    import threading
    from services.cc_launcher import CCLauncher
    from services.wine_runtimes import WineInstall
    from utils import wine_input_bridge

    prefix = tmp_path / "pfx"
    exe = prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Corporate Clash" / "CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    install = WineInstall(
        exe_path=str(exe),
        launcher="steam-proton",
        prefix_path=str(prefix),
        display_name="Test",
        metadata={"appid": "3555655912", "steam_root": str(tmp_path / "steam"), "proton_dir": str(tmp_path / "proton")},
    )

    sweeps = []
    monkeypatch.setattr(
        wine_input_bridge,
        "shutdown_for_prefix",
        lambda p: sweeps.append(p),
    )

    spawn_event = threading.Event()

    class FakeProc:
        pid = 99999
        def wait(self):
            return 0

    def fake_host_popen(*args, **kwargs):
        spawn_event.set()
        return FakeProc()

    monkeypatch.setattr("services.cc_launcher.host_popen", fake_host_popen)
    monkeypatch.setattr("services.cc_launcher._is_trusted", lambda *a, **kw: True)
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton", lambda *a, **kw: str(tmp_path / "proton"))
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available", lambda _l: True)
    monkeypatch.setattr(
        "services.wine_runtimes.build_launch_command",
        lambda install, args, extra_env: (["fake"], dict(extra_env)),
    )
    monkeypatch.setattr("services.launcher_env.build_launcher_env", lambda overrides: dict(overrides))
    monkeypatch.setattr("services.wine_runtimes.register_active_proton_compatdata", lambda _p: None)
    monkeypatch.setattr("services.wine_runtimes.unregister_active_proton_compatdata", lambda _p: None)

    launcher = CCLauncher(settings_manager=None)
    launcher.launch(
        gameserver="gs-test",
        game_token="t" * 64,
        install=install,
        username="u",
        realm_slug="production",
    )

    assert spawn_event.wait(timeout=2.0), "fake spawn never ran"
    # Sweep must have been recorded before host_popen returned (recorded
    # in module-level list during the same thread as the spawn).
    assert sweeps == [str(prefix)], f"expected pre-launch sweep, got sweeps={sweeps}"


def test_register_unregister_idempotent_and_isolated(tmp_path):
    from services.wine_runtimes import (
        register_active_proton_compatdata,
        unregister_active_proton_compatdata,
        is_proton_compatdata_active,
    )
    pa = str(tmp_path / "a")
    pb = str(tmp_path / "b")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    register_active_proton_compatdata(pa)
    register_active_proton_compatdata(pa)  # idempotent
    assert is_proton_compatdata_active(pa)
    assert not is_proton_compatdata_active(pb)

    unregister_active_proton_compatdata(pa)
    assert not is_proton_compatdata_active(pa)
    unregister_active_proton_compatdata(pa)  # idempotent on already-absent
    assert not is_proton_compatdata_active(pa)
