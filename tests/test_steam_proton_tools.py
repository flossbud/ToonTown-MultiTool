"""Tests for services.steam_proton_tools enumeration."""

import os
import pytest

from services.steam_proton_tools import (
    ProtonTool,
    enumerate_proton_tools,
)


def _make_proton(root, where, name, official, manifest_internal=None,
                 display=None):
    """Build a Proton install layout under root.

    where: "steamapps/common" (official) or "compatibilitytools.d" (user)
    name: directory basename
    manifest_internal: internal name to write into compatibilitytool.vdf
        (user) — ignored for official
    display: display_name field in compatibilitytool.vdf (user only)
    """
    base = root / where / name
    base.mkdir(parents=True)
    proton = base / "proton"
    proton.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(proton, 0o755)
    if not official:
        internal = manifest_internal or name.lower()
        disp = display or name
        (base / "compatibilitytool.vdf").write_text(
            '"compatibilitytools"\n'
            "{\n"
            '  "compat_tools"\n'
            "  {\n"
            f'    "{internal}"\n'
            "    {\n"
            '      "install_path"  "."\n'
            f'      "display_name"  "{disp}"\n'
            '      "from_oslist"   "windows"\n'
            '      "to_oslist"     "linux"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
    return str(base)


def test_empty_root_returns_empty_list(tmp_path):
    """No Steam root contents → empty list, no crash."""
    result = enumerate_proton_tools(steam_roots=[str(tmp_path)])
    assert result == []


def test_discovers_official_and_user_tools(tmp_path):
    root = tmp_path / "Steam"
    _make_proton(root, "steamapps/common", "Proton 9.0 (Beta)", official=True)
    _make_proton(root, "steamapps/common", "Proton 8.0", official=True)
    _make_proton(root, "compatibilitytools.d", "GE-Proton9-26",
                 official=False, manifest_internal="GE-Proton9-26",
                 display="GE-Proton9-26")
    _make_proton(root, "compatibilitytools.d", "Proton-CachyOS",
                 official=False, manifest_internal="proton-cachyos",
                 display="Proton-CachyOS 9.0")

    tools = enumerate_proton_tools(steam_roots=[str(root)])

    names = [t.name for t in tools]
    assert "proton-cachyos" in names
    assert "GE-Proton9-26" in names
    assert "proton_9" in names  # alias lookup
    assert "proton_8" in names


def test_skips_dir_without_proton_binary(tmp_path):
    root = tmp_path / "Steam"
    (root / "compatibilitytools.d" / "broken").mkdir(parents=True)
    # No proton binary inside "broken".
    tools = enumerate_proton_tools(steam_roots=[str(root)])
    assert tools == []


def test_user_installed_sorted_before_official(tmp_path):
    root = tmp_path / "Steam"
    _make_proton(root, "steamapps/common", "Proton 9.0 (Beta)", official=True)
    _make_proton(root, "compatibilitytools.d", "GE-Proton9-26",
                 official=False, manifest_internal="GE-Proton9-26")

    tools = enumerate_proton_tools(steam_roots=[str(root)])

    assert tools[0].source == "compatibilitytools.d"
    assert tools[1].source == "official"


def test_newest_first_within_group(tmp_path):
    root = tmp_path / "Steam"
    _make_proton(root, "compatibilitytools.d", "GE-Proton9-26",
                 official=False, manifest_internal="GE-Proton9-26")
    _make_proton(root, "compatibilitytools.d", "GE-Proton8-3",
                 official=False, manifest_internal="GE-Proton8-3")

    tools = enumerate_proton_tools(steam_roots=[str(root)])

    user_tools = [t for t in tools if t.source == "compatibilitytools.d"]
    assert user_tools[0].name == "GE-Proton9-26"  # 9.x > 8.x


def test_dedup_across_roots_by_realpath(tmp_path):
    root_a = tmp_path / "SteamA"
    root_b = tmp_path / "SteamB"
    proton_a = _make_proton(root_a, "steamapps/common",
                            "Proton 9.0 (Beta)", official=True)
    # Symlink the same Proton dir into root_b.
    (root_b / "steamapps" / "common").mkdir(parents=True)
    link = root_b / "steamapps" / "common" / "Proton 9.0 (Beta)"
    os.symlink(proton_a, link)

    tools = enumerate_proton_tools(steam_roots=[str(root_a), str(root_b)])

    proton_9 = [t for t in tools if t.name == "proton_9"]
    assert len(proton_9) == 1
    assert proton_9[0].steam_root == str(root_a)  # first-seen wins


def test_display_name_uses_compat_tool_vdf(tmp_path):
    root = tmp_path / "Steam"
    _make_proton(root, "compatibilitytools.d", "Proton-CachyOS-9.0",
                 official=False, manifest_internal="proton-cachyos",
                 display="Proton-CachyOS (special build)")

    tools = enumerate_proton_tools(steam_roots=[str(root)])

    cachyos = [t for t in tools if t.name == "proton-cachyos"][0]
    assert cachyos.display_name == "Proton-CachyOS (special build)"


def test_version_key_extraction():
    """Direct unit test of the version-tuple extraction heuristic."""
    from services.steam_proton_tools import _version_key_from_name
    assert _version_key_from_name("Proton 9.0 (Beta)") == (9, 0)
    assert _version_key_from_name("GE-Proton9-26") == (9, 26)
    assert _version_key_from_name("Proton-CachyOS-9.0-20251214") == (9, 0, 20251214)
    assert _version_key_from_name("Proton - Experimental") == ()
