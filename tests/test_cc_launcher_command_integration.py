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
