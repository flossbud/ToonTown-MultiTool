"""Wine front-end discovery, classification, and launch-command building.

All Linux-Wine specifics live here. Pure logic; no Qt dependencies.
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WineInstall:
    """A discovered Corporate Clash installation.

    Attributes
    ----------
    exe_path : str
        Absolute host path to CorporateClash.exe.
    launcher : str
        One of: "bottles", "lutris", "steam-proton", "wine", "native".
    prefix_path : str | None
        Wine prefix root. None for the "native" Windows case.
    display_name : str
        Human-readable label, e.g. "Bottles · Corporate-Clash".
    metadata : dict
        Launcher-specific extras (bottle_name, lutris_game_id, steam_appid,
        runner_path, etc.). Not part of the install signature.
    """

    exe_path: str
    launcher: str
    prefix_path: str | None
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


def install_signature(install: WineInstall) -> str:
    """Return a stable identifier for an install.

    The signature depends only on (launcher, prefix_path, exe_path) realpaths,
    so display_name changes and metadata changes don't invalidate it.
    """
    parts = [
        install.launcher,
        os.path.realpath(install.prefix_path) if install.prefix_path else "",
        os.path.realpath(install.exe_path),
    ]
    raw = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def host_to_windows_path(host_path: str, prefix_path: str) -> str:
    """Translate a host path inside a Wine prefix to its Windows equivalent.

    Example
    -------
    host_path   = "<prefix>/drive_c/users/foo/bar.exe"
    prefix_path = "<prefix>"
    returns     = "C:\\users\\foo\\bar.exe"

    Raises ValueError if host_path is not under prefix_path/drive_c.
    """
    drive_c = os.path.realpath(os.path.join(prefix_path, "drive_c"))
    host_real = os.path.realpath(host_path)
    try:
        rel = os.path.relpath(host_real, drive_c)
    except ValueError as e:
        raise ValueError(
            f"{host_path!r} is not inside {drive_c!r}"
        ) from e
    if rel.startswith(".."):
        raise ValueError(f"{host_path!r} is not inside {drive_c!r}")
    return "C:\\" + rel.replace("/", "\\")


_EXE_NAME = "CorporateClash.exe"


def _native_search_paths() -> list[str]:
    """Return the Windows-native search list. Identical to the old
    CC_ENGINE_SEARCH_PATHS, kept here so the module is self-contained."""
    return [
        os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")),
            "Corporate Clash",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            "Corporate Clash",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
            "Corporate Clash",
        ),
        os.path.expanduser("~/Games/Corporate Clash"),
    ]


def discover_native_windows() -> list[WineInstall]:
    """Return installs reachable via the Windows-native search list.

    Returns an empty list if no install is found. Runs on every platform
    (it is the only non-Wine discovery and is harmless on Linux).
    """
    results: list[WineInstall] = []
    seen: set[str] = set()
    for path in _native_search_paths():
        exe = os.path.join(path, _EXE_NAME)
        if not os.path.isfile(exe):
            continue
        real = os.path.realpath(exe)
        if real in seen:
            continue
        seen.add(real)
        results.append(
            WineInstall(
                exe_path=exe,
                launcher="native",
                prefix_path=None,
                display_name=f"Corporate Clash ({path})",
                metadata={"search_path": path},
            )
        )
    return results


_IN_PREFIX_GLOBS = [
    "drive_c/users/*/AppData/Local/Corporate Clash/CorporateClash.exe",
    "drive_c/Program Files/Corporate Clash/CorporateClash.exe",
    "drive_c/Program Files (x86)/Corporate Clash/CorporateClash.exe",
]


def _find_cc_in_prefix(prefix_path: str) -> list[str]:
    """Return absolute paths to CorporateClash.exe inside a Wine prefix."""
    results: list[str] = []
    for pattern in _IN_PREFIX_GLOBS:
        for match in glob.glob(os.path.join(prefix_path, pattern)):
            if os.path.isfile(match):
                results.append(match)
    return results


def discover_plain_wine() -> list[WineInstall]:
    """Find CC in ~/.wine and ~/.local/share/wineprefixes/*/."""
    if sys.platform == "win32":
        return []
    results: list[WineInstall] = []
    candidates: list[str] = []
    home = os.path.expanduser("~")
    dot_wine = os.path.join(home, ".wine")
    if os.path.isdir(dot_wine):
        candidates.append(dot_wine)
    wineprefixes_root = os.path.join(home, ".local", "share", "wineprefixes")
    if os.path.isdir(wineprefixes_root):
        for entry in sorted(os.listdir(wineprefixes_root)):
            full = os.path.join(wineprefixes_root, entry)
            if os.path.isdir(full):
                candidates.append(full)
    seen: set[str] = set()
    for prefix in candidates:
        for exe in _find_cc_in_prefix(prefix):
            real = os.path.realpath(exe)
            if real in seen:
                continue
            seen.add(real)
            name = os.path.basename(prefix.rstrip(os.sep))
            results.append(
                WineInstall(
                    exe_path=exe,
                    launcher="wine",
                    prefix_path=prefix,
                    display_name=f"Wine · {name}",
                    metadata={"prefix_name": name},
                )
            )
    return results


_BOTTLES_ROOTS = [
    ("~/.var/app/com.usebottles.bottles/data/bottles/bottles", "flatpak"),
    ("~/.local/share/bottles/bottles", "native"),
]


def _read_bottle_name(bottle_dir: str) -> str | None:
    """Parse bottle.yml's Name field. Returns None if unreadable."""
    bottle_yml = os.path.join(bottle_dir, "bottle.yml")
    if not os.path.isfile(bottle_yml):
        return None
    try:
        import yaml  # PyYAML — Linux-only, lazy-imported so this module
        # imports cleanly on Windows where the dep is not installed.
        with open(bottle_yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        name = data.get("Name")
        return str(name) if name else None
    except Exception:
        return None


def discover_bottles() -> list[WineInstall]:
    """Find CC inside Bottles prefixes (Flatpak and native)."""
    if sys.platform == "win32":
        return []
    results: list[WineInstall] = []
    seen: set[str] = set()
    for root_template, distribution in _BOTTLES_ROOTS:
        root = os.path.expanduser(root_template)
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            bottle_dir = os.path.join(root, entry)
            if not os.path.isdir(bottle_dir):
                continue
            for exe in _find_cc_in_prefix(bottle_dir):
                real = os.path.realpath(exe)
                if real in seen:
                    continue
                seen.add(real)
                bottle_name = _read_bottle_name(bottle_dir) or entry
                results.append(
                    WineInstall(
                        exe_path=exe,
                        launcher="bottles",
                        prefix_path=bottle_dir,
                        display_name=f"Bottles · {bottle_name}",
                        metadata={
                            "bottle_name": entry,
                            "bottle_display_name": bottle_name,
                            "distribution": distribution,
                        },
                    )
                )
    return results


_LUTRIS_CONFIG_ROOTS = [
    "~/.config/lutris/games",
    "~/.var/app/net.lutris.Lutris/config/lutris/games",
]


def _parse_lutris_yaml(yml_path: str) -> tuple[str | None, str | None, str | None]:
    """Return (prefix_path, name, runner) from a Lutris game YAML, or
    (None, None, None) if unparseable."""
    try:
        import yaml  # PyYAML — Linux-only, lazy-imported.
        with open(yml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Prefix lives under "game" or "wine" depending on Lutris version.
        prefix = None
        for section in ("game", "wine"):
            block = data.get(section)
            if isinstance(block, dict) and block.get("prefix"):
                prefix = str(block["prefix"])
                break
        name = data.get("name")
        runner = data.get("runner")
        return prefix, (str(name) if name else None), (str(runner) if runner else None)
    except Exception:
        return None, None, None


def discover_lutris() -> list[WineInstall]:
    """Find CC inside Wine prefixes managed by Lutris."""
    if sys.platform == "win32":
        return []
    results: list[WineInstall] = []
    seen: set[str] = set()
    for root_template in _LUTRIS_CONFIG_ROOTS:
        root = os.path.expanduser(root_template)
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            if not entry.endswith(".yml"):
                continue
            yml_path = os.path.join(root, entry)
            prefix, name, runner = _parse_lutris_yaml(yml_path)
            if not prefix or runner != "wine":
                continue
            if not os.path.isdir(prefix):
                continue
            for exe in _find_cc_in_prefix(prefix):
                real = os.path.realpath(exe)
                if real in seen:
                    continue
                seen.add(real)
                slug = entry[:-4]
                display = name or slug
                results.append(
                    WineInstall(
                        exe_path=exe,
                        launcher="lutris",
                        prefix_path=prefix,
                        display_name=f"Lutris · {display}",
                        metadata={"lutris_slug": slug, "lutris_name": name},
                    )
                )
    return results


_STEAM_ROOTS = [
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
]


def _read_proton_dir(compatdata_dir: str) -> str | None:
    """Return the Proton install directory recorded in config_info, or None."""
    cfg = os.path.join(compatdata_dir, "config_info")
    if not os.path.isfile(cfg):
        return None
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            first = f.readline().strip()
        return first or None
    except Exception:
        return None


def _read_shortcut_name(steam_root: str, appid: str) -> str | None:
    """Best-effort: extract a non-Steam shortcut name from shortcuts.vdf.

    shortcuts.vdf is a binary VDF blob. Each shortcut entry stores keys
    with a type-byte prefix: \x02 for int32, \x01 for string. Steam writes
    them in this order per entry: appid (int), AppName (string), Exe, etc.

    We scan for "\x02appid\x00<le-uint32>" remembering the most recent
    appid seen, then on the next "\x01AppName\x00<name>\x00" we return the
    name if its remembered appid matches the target. Returns None on any
    parse failure.
    """
    userdata = os.path.join(steam_root, "userdata")
    if not os.path.isdir(userdata):
        return None
    try:
        target = int(appid)
        for uid in os.listdir(userdata):
            if not uid.isdigit():
                continue
            shortcuts = os.path.join(userdata, uid, "config", "shortcuts.vdf")
            if not os.path.isfile(shortcuts):
                continue
            with open(shortcuts, "rb") as f:
                blob = f.read()
            idx = 0
            last_appid: int | None = None
            while idx < len(blob):
                if blob[idx:idx+7] == b"\x02appid\x00" and idx + 11 <= len(blob):
                    last_appid = int.from_bytes(
                        blob[idx+7:idx+11], "little", signed=False
                    )
                    idx += 11
                    continue
                if blob[idx:idx+9] == b"\x01AppName\x00":
                    end = blob.find(b"\x00", idx + 9)
                    if end == -1:
                        break
                    if last_appid == target:
                        try:
                            return blob[idx+9:end].decode("utf-8")
                        except UnicodeDecodeError:
                            return None
                    idx = end + 1
                    continue
                idx += 1
    except Exception:
        return None
    return None


def discover_steam_proton() -> list[WineInstall]:
    """Find CC inside Steam Proton compatdata prefixes."""
    if sys.platform == "win32":
        return []
    results: list[WineInstall] = []
    seen: set[str] = set()
    for root_template in _STEAM_ROOTS:
        steam_root = os.path.expanduser(root_template)
        compatdata = os.path.join(steam_root, "steamapps", "compatdata")
        if not os.path.isdir(compatdata):
            continue
        for entry in sorted(os.listdir(compatdata)):
            if not entry.isdigit():
                continue
            pfx = os.path.join(compatdata, entry, "pfx")
            if not os.path.isdir(pfx):
                continue
            for exe in _find_cc_in_prefix(pfx):
                real = os.path.realpath(exe)
                if real in seen:
                    continue
                seen.add(real)
                proton_dir = _read_proton_dir(os.path.join(compatdata, entry))
                name = _read_shortcut_name(steam_root, entry) or f"Steam · {entry}"
                results.append(
                    WineInstall(
                        exe_path=exe,
                        launcher="steam-proton",
                        prefix_path=pfx,
                        display_name=f"Steam · {name}" if not name.startswith("Steam · ") else name,
                        metadata={
                            "appid": entry,
                            "steam_root": steam_root,
                            "proton_dir": proton_dir,
                        },
                    )
                )
    return results


def _ancestor_with_marker(start: str, marker_basename: str) -> str | None:
    """Walk up from start, return the first ancestor containing marker_basename."""
    current = os.path.realpath(start)
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        if os.path.exists(os.path.join(current, marker_basename)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def classify_path(exe_path: str) -> WineInstall | None:
    """Inspect on-disk markers to infer which launcher owns this path.

    Returns None when no recognizable launcher signature is present.
    """
    if not os.path.isfile(exe_path):
        return None
    real = os.path.realpath(exe_path)

    # Bottles: any ancestor contains a bottle.yml
    bottle_root = _ancestor_with_marker(os.path.dirname(real), "bottle.yml")
    if bottle_root:
        bottle_name = _read_bottle_name(bottle_root) or os.path.basename(bottle_root)
        return WineInstall(
            exe_path=exe_path,
            launcher="bottles",
            prefix_path=bottle_root,
            display_name=f"Bottles · {bottle_name}",
            metadata={
                "bottle_name": os.path.basename(bottle_root),
                "bottle_display_name": bottle_name,
            },
        )

    # Steam Proton: ancestor chain contains compatdata/<digits>/pfx
    parts = real.split(os.sep)
    for i in range(len(parts) - 2):
        if parts[i] == "compatdata" and parts[i + 1].isdigit() and parts[i + 2] == "pfx":
            appid = parts[i + 1]
            pfx = os.sep + os.path.join(*parts[: i + 3])
            steam_root = os.sep + os.path.join(*parts[: i - 1]) if i >= 1 else None
            proton_dir = _read_proton_dir(os.path.dirname(pfx))
            name = _read_shortcut_name(steam_root, appid) if steam_root else None
            display = name or f"Steam · {appid}"
            return WineInstall(
                exe_path=exe_path,
                launcher="steam-proton",
                prefix_path=pfx,
                display_name=display if display.startswith("Steam · ") else f"Steam · {display}",
                metadata={"appid": appid, "steam_root": steam_root, "proton_dir": proton_dir},
            )

    # Lutris: cross-reference Lutris YAMLs
    for root_template in _LUTRIS_CONFIG_ROOTS:
        root = os.path.expanduser(root_template)
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            if not entry.endswith(".yml"):
                continue
            prefix, name, runner = _parse_lutris_yaml(os.path.join(root, entry))
            if runner != "wine" or not prefix:
                continue
            if real.startswith(os.path.realpath(prefix) + os.sep):
                slug = entry[:-4]
                display = name or slug
                return WineInstall(
                    exe_path=exe_path,
                    launcher="lutris",
                    prefix_path=prefix,
                    display_name=f"Lutris · {display}",
                    metadata={"lutris_slug": slug, "lutris_name": name},
                )

    # Plain Wine: ancestor with a dosdevices/c: marker
    dosdevices_root = _ancestor_with_marker(os.path.dirname(real), "dosdevices")
    if dosdevices_root:
        name = os.path.basename(dosdevices_root.rstrip(os.sep))
        return WineInstall(
            exe_path=exe_path,
            launcher="wine",
            prefix_path=dosdevices_root,
            display_name=f"Wine · {name}",
            metadata={"prefix_name": name},
        )

    return None


def build_launch_command(
    install: WineInstall,
    args: list[str],
    extra_env: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Return (argv, env_overrides) suitable for subprocess.Popen.

    extra_env is the env the *game* should see (e.g. CC_OSST_TOKEN). It is
    merged into the result; the caller is responsible for passing this dict
    to build_launcher_env().
    """
    env: dict[str, str] = dict(extra_env)

    if install.launcher == "native":
        return [install.exe_path, *args], env

    if install.launcher == "wine":
        if not install.prefix_path:
            raise ValueError("wine launcher requires prefix_path")
        env["WINEPREFIX"] = install.prefix_path
        return ["wine", install.exe_path, *args], env

    if install.launcher == "lutris":
        if not install.prefix_path:
            raise ValueError("lutris launcher requires prefix_path")
        env["WINEPREFIX"] = install.prefix_path
        return ["wine", install.exe_path, *args], env

    if install.launcher == "steam-proton":
        if not install.prefix_path:
            raise ValueError("steam-proton launcher requires prefix_path")
        proton_dir = install.metadata.get("proton_dir")
        steam_root = install.metadata.get("steam_root")
        if not proton_dir:
            raise ValueError("steam-proton launcher requires metadata.proton_dir")
        if not steam_root:
            raise ValueError("steam-proton launcher requires metadata.steam_root")
        proton_bin = os.path.join(proton_dir, "proton")
        env["STEAM_COMPAT_DATA_PATH"] = os.path.dirname(install.prefix_path)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = steam_root
        return [proton_bin, "run", install.exe_path, *args], env

    if install.launcher == "bottles":
        if not install.prefix_path:
            raise ValueError("bottles launcher requires prefix_path")
        # bottles-cli identifies bottles by the display name from bottle.yml
        # ("Corporate Clash"), not the filesystem-sanitized dir name
        # ("Corporate-Clash"). Discovery captures both; prefer the display
        # name and fall back to the dir basename if bottle.yml was missing.
        bottle_name = (
            install.metadata.get("bottle_display_name")
            or install.metadata.get("bottle_name")
        )
        if not bottle_name:
            raise ValueError("bottles launcher requires metadata.bottle_name")
        # We pass the UNIX host path of the executable, not the Windows
        # form. Two reasons:
        #   1. bottles-cli's WineExecutor.__get_cwd has a quoting bug when
        #      exec_path is a Windows path: it splits the shlex-quoted
        #      path on '\\' then drops the last segment, which strips the
        #      closing single quote and produces an unbalanced shell
        #      string fed to `winepath --unix`. The Unix-path branch in
        #      __get_cwd skips the broken slice entirely.
        #   2. Unix paths trigger the `is_unix` branch in start.py, which
        #      uses `start /unix /wait <path>` — fine for our purposes.
        distribution = install.metadata.get("distribution", "flatpak")
        if distribution == "flatpak":
            base = [
                "flatpak", "run",
                "--command=bottles-cli",
                "com.usebottles.bottles",
            ]
        else:
            base = ["bottles-cli"]
        # bottles-cli `run` takes args as positional trailing tokens, but
        # argparse will re-interpret a leading dash on any of them as a
        # bottles-cli flag. The POSIX terminator `--` stops bottles-cli's
        # flag parser and forwards everything afterward to the executable
        # verbatim. (Under the new CC launcher protocol args is empty —
        # credentials go via env vars — but keep the `--` for safety.)
        cmd = [*base, "run", "-b", bottle_name, "-e", install.exe_path, "--", *args]
        return cmd, env

    raise ValueError(f"Unsupported launcher: {install.launcher}")


_LAUNCHER_PRIORITY = ["bottles", "lutris", "steam-proton", "wine", "native"]


def _host_command_exists(name: str) -> bool:
    """True if `which <name>` succeeds on the host system.

    Routes through utils.host_spawn so that when TTMT itself runs inside a
    Flatpak sandbox, this queries the host PATH (via flatpak-spawn --host)
    rather than the sandbox PATH.
    """
    from utils.host_spawn import host_check_output
    try:
        out = host_check_output(["which", name], timeout=2)
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return bool(out and out.strip())
    except Exception:
        return False


def is_launcher_available(launcher: str) -> bool:
    """Check whether the launcher's required runtime is reachable.

    Probes the host system via utils.host_spawn so that this returns
    correct results when TTMT itself runs inside a Flatpak sandbox.
    """
    print(f"[wine_runtimes] is_launcher_available({launcher!r}) probing…")
    if launcher == "native":
        print(f"[wine_runtimes] is_launcher_available: native -> True")
        return True
    if launcher in ("wine", "lutris"):
        ok = _host_command_exists("wine")
        print(f"[wine_runtimes] is_launcher_available: {launcher} -> wine on PATH: {ok}")
        return ok
    if launcher == "bottles":
        if _host_command_exists("bottles-cli"):
            print("[wine_runtimes] is_launcher_available: bottles -> bottles-cli on PATH: True")
            return True
        print("[wine_runtimes] is_launcher_available: bottles -> bottles-cli not on PATH, "
              "falling back to flatpak probe")
        if not _host_command_exists("flatpak"):
            print("[wine_runtimes] is_launcher_available: bottles -> flatpak not on PATH: False")
            return False
        from utils.host_spawn import host_run

        def _decode(b):
            if b is None:
                return ""
            if isinstance(b, bytes):
                b = b.decode("utf-8", "replace")
            return b.strip()

        # Probe 1: `flatpak info` defaults to both scopes, but on some
        # setups it fails when the app is installed --user only and the
        # subprocess env is missing the right XDG hints.
        try:
            res = host_run(
                ["flatpak", "info", "com.usebottles.bottles"],
                capture_output=True,
                timeout=10,
            )
            print(f"[wine_runtimes] is_launcher_available: bottles -> "
                  f"flatpak info rc={res.returncode} "
                  f"stderr={_decode(res.stderr)!r} stdout_head={_decode(res.stdout)[:120]!r}")
            if res.returncode == 0:
                return True
        except Exception as e:
            print(f"[wine_runtimes] is_launcher_available: bottles -> "
                  f"flatpak info raised {type(e).__name__}: {e}")

        # Probe 2: explicit per-scope info. --user finds user installs
        # even when the default search misses them; --system covers the
        # opposite case.
        for scope in ("--user", "--system"):
            try:
                res = host_run(
                    ["flatpak", "info", scope, "com.usebottles.bottles"],
                    capture_output=True,
                    timeout=10,
                )
                print(f"[wine_runtimes] is_launcher_available: bottles -> "
                      f"flatpak info {scope} rc={res.returncode} "
                      f"stderr={_decode(res.stderr)!r}")
                if res.returncode == 0:
                    return True
            except Exception as e:
                print(f"[wine_runtimes] is_launcher_available: bottles -> "
                      f"flatpak info {scope} raised {type(e).__name__}: {e}")

        # Probe 3: `flatpak list --app` always returns 0; grep for the id.
        # Works across both scopes without env quirks.
        try:
            res = host_run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True,
                timeout=10,
            )
            apps = _decode(res.stdout)
            found = "com.usebottles.bottles" in apps.split()
            print(f"[wine_runtimes] is_launcher_available: bottles -> "
                  f"flatpak list rc={res.returncode} contains_bottles={found}")
            if found:
                return True
        except Exception as e:
            print(f"[wine_runtimes] is_launcher_available: bottles -> "
                  f"flatpak list raised {type(e).__name__}: {e}")

        # Probe 4: filesystem evidence — a bottles-shaped install was
        # already discovered (we wouldn't be in this branch otherwise),
        # so accepting the per-user flatpak data dir as proof of install
        # is consistent with discovery's existing trust signals.
        user_app_dir = os.path.expanduser("~/.var/app/com.usebottles.bottles")
        if os.path.isdir(user_app_dir):
            print(f"[wine_runtimes] is_launcher_available: bottles -> "
                  f"~/.var/app/com.usebottles.bottles present (per-user install): True")
            return True

        print("[wine_runtimes] is_launcher_available: bottles -> all probes failed: False")
        return False
    if launcher == "steam-proton":
        # Availability is per-install (proton_dir from metadata); generic
        # check just verifies steam exists somewhere.
        for root_template in _STEAM_ROOTS:
            if os.path.isdir(os.path.expanduser(root_template)):
                print(f"[wine_runtimes] is_launcher_available: steam-proton -> "
                      f"found root {root_template}: True")
                return True
        print("[wine_runtimes] is_launcher_available: steam-proton -> no steam root found: False")
        return False
    print(f"[wine_runtimes] is_launcher_available: unknown launcher {launcher!r}: False")
    return False


_BOTTLE_ENV_ALLOWLIST_KEY = "Inherited_Environment_Variables"


def ensure_bottle_env_allowlist(prefix_path: str, required_keys: list[str]) -> bool:
    """Make sure each key in ``required_keys`` is present in the bottle's
    ``Inherited_Environment_Variables`` allowlist.

    Bottles' ``Limit_System_Environment`` flag, when true (the default in
    modern Bottles versions), instructs ``WineEnv`` to inherit ONLY the
    env vars whose names appear in ``Inherited_Environment_Variables``.
    Anything else — including the env vars CC's new launcher protocol
    needs (``TT_PLAYCOOKIE``, ``TT_GAMESERVER``, ``LAUNCHER_USER``,
    ``REALM``, ``SENTRY_ENVIRONMENT``) — is silently dropped before the
    game is invoked. CC.exe then has no auth context, the gameserver
    kicks the connection, and the game quietly exits with rc=0 and no
    log file written.

    Append-only: existing keys keep their order; we add missing keys at
    the end. A ``.bak`` is written next to the YAML before mutating.
    Returns True if the file was modified, False if no change was
    needed or if anything went wrong (the launch then proceeds in best-
    effort mode, surfacing whatever bottles does without the allowlist
    fix).
    """
    if not prefix_path:
        return False
    bottle_yml = os.path.join(prefix_path, "bottle.yml")
    if not os.path.isfile(bottle_yml):
        print(f"[wine_runtimes] ensure_bottle_env_allowlist: no bottle.yml at {bottle_yml}")
        return False
    try:
        import yaml
    except ImportError:
        print("[wine_runtimes] ensure_bottle_env_allowlist: PyYAML unavailable; skipping")
        return False
    try:
        with open(bottle_yml) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[wine_runtimes] ensure_bottle_env_allowlist: read failed {type(e).__name__}: {e}")
        return False

    existing = list(cfg.get(_BOTTLE_ENV_ALLOWLIST_KEY) or [])
    existing_set = set(existing)
    missing = [k for k in required_keys if k and k not in existing_set]
    if not missing:
        return False

    cfg[_BOTTLE_ENV_ALLOWLIST_KEY] = existing + missing

    backup = bottle_yml + ".bak"
    try:
        if not os.path.exists(backup):
            shutil.copy2(bottle_yml, backup)
        with open(bottle_yml, "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
        print(f"[wine_runtimes] ensure_bottle_env_allowlist: added {missing} to {bottle_yml}")
        return True
    except Exception as e:
        print(f"[wine_runtimes] ensure_bottle_env_allowlist: write failed {type(e).__name__}: {e}")
        return False


def discover_cc_installs() -> list[WineInstall]:
    """Return all detected CC installs, deduped by realpath, sorted by
    launcher preference: bottles > lutris > steam-proton > wine > native.
    """
    discoveries = [
        *discover_bottles(),
        *discover_lutris(),
        *discover_steam_proton(),
        *discover_plain_wine(),
        *discover_native_windows(),
    ]
    seen: dict[str, WineInstall] = {}
    priority = {name: i for i, name in enumerate(_LAUNCHER_PRIORITY)}
    for inst in discoveries:
        real = os.path.realpath(inst.exe_path)
        existing = seen.get(real)
        if existing is None or priority.get(inst.launcher, 99) < priority.get(existing.launcher, 99):
            seen[real] = inst
    return sorted(seen.values(), key=lambda i: priority.get(i.launcher, 99))
