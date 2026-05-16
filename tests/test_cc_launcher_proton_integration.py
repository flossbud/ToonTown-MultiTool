"""Integration tests for CCLauncher.launch wiring of the Proton resolver."""

import os
import sys
import pytest
from PySide6.QtCore import QCoreApplication

from services.wine_runtimes import WineInstall
from services import cc_launcher as ccl


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


class _FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _steam_proton_install(tmp_path, proton_dir):
    pfx = tmp_path / "compatdata/9999/pfx"
    pfx.mkdir(parents=True)
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return WineInstall(
        exe_path=str(exe),
        launcher="steam-proton",
        prefix_path=str(pfx),
        display_name="Steam · CC",
        metadata={
            "appid": "9999",
            "steam_root": str(tmp_path),
            "proton_dir": proton_dir,
        },
    )


def _make_proton_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir(parents=True)
    bin_ = d / "proton"
    bin_.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(bin_, 0o755)
    return str(d)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only path")
def test_override_proton_used_in_argv(qapp, tmp_path, monkeypatch):
    """Linux + steam-proton + override → argv uses override's proton."""
    override = _make_proton_dir(tmp_path, "OverrideProton")
    config_info = _make_proton_dir(tmp_path, "ConfigInfoProton")
    install = _steam_proton_install(tmp_path, proton_dir=config_info)
    sm = _FakeSettings({"cc_steam_proton_override": override})
    captured = {}

    class _Proc:
        def __init__(self): self.pid = 9999
        def poll(self): return None
        def wait(self): return 0
    monkeypatch.setattr(ccl, "host_popen",
                        lambda cmd, **kw: (captured.update(cmd=cmd) or _Proc()))
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: True)
    launcher = ccl.CCLauncher(settings_manager=sm)

    launcher.launch(
        gameserver="gs.example",
        game_token="tok",
        install=install,
        username="user",
    )
    # Threaded; wait for the child wait() to return.
    import time
    for _ in range(50):
        if "cmd" in captured:
            break
        time.sleep(0.02)

    assert captured["cmd"][0] == os.path.join(override, "proton")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only path")
def test_no_override_uses_cascade_resolved_path(qapp, tmp_path, monkeypatch):
    """No override → resolver returns config_info; argv reflects it."""
    config_info = _make_proton_dir(tmp_path, "ConfigInfoProton")
    install = _steam_proton_install(tmp_path, proton_dir=config_info)
    sm = _FakeSettings({})
    captured = {}

    class _Proc:
        def __init__(self): self.pid = 9999
        def poll(self): return None
        def wait(self): return 0
    monkeypatch.setattr(ccl, "host_popen",
                        lambda cmd, **kw: (captured.update(cmd=cmd) or _Proc()))
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: True)
    monkeypatch.setattr(ccl, "steam_compat_choice", lambda r, a: None)
    launcher = ccl.CCLauncher(settings_manager=sm)

    launcher.launch(gameserver="g", game_token="t", install=install,
                    username="u")
    import time
    for _ in range(50):
        if "cmd" in captured:
            break
        time.sleep(0.02)

    assert captured["cmd"][0] == os.path.join(config_info, "proton")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only path")
def test_bottles_install_does_not_call_resolver(qapp, tmp_path, monkeypatch):
    """Bottles launcher → resolver MUST NOT be called."""
    pfx = tmp_path / "bottle"
    exe = pfx / "drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    (pfx / "bottle.yml").write_text("Name: X\n")
    install = WineInstall(
        exe_path=str(exe), launcher="bottles", prefix_path=str(pfx),
        display_name="x", metadata={"bottle_name": "x", "distribution": "native"},
    )
    sm = _FakeSettings({"cc_steam_proton_override": "/should/be/ignored"})
    called = {"n": 0}

    def _resolver_should_not_be_called(*a, **kw):
        called["n"] += 1
        return None
    monkeypatch.setattr(ccl, "resolve_effective_proton",
                        _resolver_should_not_be_called)
    monkeypatch.setattr(ccl, "host_popen", lambda cmd, **kw:
                        type("P", (), {"pid": 1, "poll": lambda s: None,
                                       "wait": lambda s: 0})())
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: True)
    monkeypatch.setattr("services.wine_runtimes.ensure_bottle_env_allowlist",
                        lambda *a, **kw: None)
    launcher = ccl.CCLauncher(settings_manager=sm)

    launcher.launch(gameserver="g", game_token="t", install=install,
                    username="u")
    import time
    time.sleep(0.1)

    assert called["n"] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only path")
def test_resolver_none_emits_launch_failed(qapp, tmp_path, monkeypatch):
    install = _steam_proton_install(tmp_path, proton_dir=None)
    sm = _FakeSettings({})
    monkeypatch.setattr("services.wine_runtimes.is_launcher_available",
                        lambda lk: True)
    monkeypatch.setattr(ccl, "resolve_effective_proton",
                        lambda inst, sm_: None)
    spawn_called = {"n": 0}
    monkeypatch.setattr(ccl, "host_popen", lambda *a, **kw:
                        spawn_called.update(n=spawn_called["n"] + 1))

    failed_msgs = []
    launcher = ccl.CCLauncher(settings_manager=sm)
    launcher.launch_failed.connect(failed_msgs.append)

    launcher.launch(gameserver="g", game_token="t", install=install,
                    username="u")

    assert len(failed_msgs) == 1
    assert "no Proton compatibility tool is installed" in failed_msgs[0]
    assert spawn_called["n"] == 0
