"""Tests for cc_launcher.resolve_effective_proton cascade logic."""

import os
import pytest

from services.wine_runtimes import WineInstall
from services.steam_proton_tools import ProtonTool
from services import cc_launcher as ccl


class _FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _proton_dir(tmp_path, name) -> str:
    d = tmp_path / name
    d.mkdir(parents=True)
    bin_ = d / "proton"
    bin_.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(bin_, 0o755)
    return str(d)


def _install(tmp_path, *, proton_dir=None, steam_root="/fake/root",
             appid="9999"):
    pfx = tmp_path / "prefix"
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
            "appid": appid,
            "steam_root": steam_root,
            "proton_dir": proton_dir,
        },
    )


def test_override_path_wins_when_valid(tmp_path):
    override = _proton_dir(tmp_path, "OverrideProton")
    install = _install(tmp_path, proton_dir=_proton_dir(tmp_path, "ConfigInfoProton"))
    sm = _FakeSettings({"cc_steam_proton_override": override})

    result = ccl.resolve_effective_proton(install, sm)

    assert result == override


def test_stale_override_clears_setting_and_falls_through(tmp_path, monkeypatch):
    config_info = _proton_dir(tmp_path, "ConfigInfoProton")
    install = _install(tmp_path, proton_dir=config_info)
    stale = str(tmp_path / "GoneProton")  # path doesn't exist
    sm = _FakeSettings({"cc_steam_proton_override": stale})
    # Block step 2 by ensuring no steam_compat_choice match.
    monkeypatch.setattr(ccl, "steam_compat_choice", lambda root, app: None)

    result = ccl.resolve_effective_proton(install, sm)

    assert result == config_info
    assert sm.values["cc_steam_proton_override"] == ""  # cleared


def test_compatmapping_match_returns_tool_dir(tmp_path, monkeypatch):
    tool_dir = _proton_dir(tmp_path, "ProtonCachyOS")
    install = _install(tmp_path, proton_dir=None)
    sm = _FakeSettings({})
    monkeypatch.setattr(ccl, "steam_compat_choice",
                        lambda root, app: "proton-cachyos")
    monkeypatch.setattr(
        ccl, "enumerate_proton_tools",
        lambda: [ProtonTool(
            name="proton-cachyos", display_name="Proton-CachyOS",
            proton_dir=tool_dir, source="compatibilitytools.d",
            steam_root="/fake/root", version_key=(9, 0),
        )],
    )

    assert ccl.resolve_effective_proton(install, sm) == tool_dir


def test_compatmapping_unmatched_falls_through(tmp_path, monkeypatch):
    config_info = _proton_dir(tmp_path, "ConfigInfoProton")
    install = _install(tmp_path, proton_dir=config_info)
    sm = _FakeSettings({})
    monkeypatch.setattr(ccl, "steam_compat_choice",
                        lambda root, app: "ghost-proton-not-installed")
    monkeypatch.setattr(ccl, "enumerate_proton_tools", lambda: [])

    assert ccl.resolve_effective_proton(install, sm) == config_info


def test_config_info_used_when_no_override_or_mapping(tmp_path, monkeypatch):
    config_info = _proton_dir(tmp_path, "ConfigInfoProton")
    install = _install(tmp_path, proton_dir=config_info)
    sm = _FakeSettings({})
    monkeypatch.setattr(ccl, "steam_compat_choice", lambda root, app: None)

    assert ccl.resolve_effective_proton(install, sm) == config_info


def test_stale_config_info_falls_through_to_fallback(tmp_path, monkeypatch):
    fallback_dir = _proton_dir(tmp_path, "FallbackProton")
    install = _install(tmp_path, proton_dir=str(tmp_path / "GoneCfg"))
    sm = _FakeSettings({})
    monkeypatch.setattr(ccl, "steam_compat_choice", lambda root, app: None)
    monkeypatch.setattr(
        ccl, "enumerate_proton_tools",
        lambda: [ProtonTool(
            name="ge-proton", display_name="GE-Proton9-26",
            proton_dir=fallback_dir, source="compatibilitytools.d",
            steam_root="/fake/root", version_key=(9, 26),
        )],
    )

    assert ccl.resolve_effective_proton(install, sm) == fallback_dir


def test_returns_none_when_nothing_installed(tmp_path, monkeypatch):
    install = _install(tmp_path, proton_dir=None)
    sm = _FakeSettings({})
    monkeypatch.setattr(ccl, "steam_compat_choice", lambda root, app: None)
    monkeypatch.setattr(ccl, "enumerate_proton_tools", lambda: [])

    assert ccl.resolve_effective_proton(install, sm) is None


def test_missing_steam_root_skips_step2(tmp_path, monkeypatch):
    """If install.metadata has no steam_root, step 2 is skipped cleanly."""
    config_info = _proton_dir(tmp_path, "ConfigInfoProton")
    install = WineInstall(
        exe_path=str(tmp_path / "fake.exe"),
        launcher="steam-proton",
        prefix_path=str(tmp_path),
        display_name="x",
        metadata={"appid": "9999", "proton_dir": config_info},  # no steam_root
    )
    sm = _FakeSettings({})
    called = {"n": 0}
    def _fake_choice(root, app):
        called["n"] += 1
        return None
    monkeypatch.setattr(ccl, "steam_compat_choice", _fake_choice)

    assert ccl.resolve_effective_proton(install, sm) == config_info
    assert called["n"] == 0  # step 2 was skipped, not called with None
