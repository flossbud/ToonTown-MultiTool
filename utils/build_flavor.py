"""Single source of truth for build flavor (stable vs beta).

The Arch ttmt-beta package's launcher sets TTMT_BETA=1 before exec'ing
main.py; the Windows beta installer drops a .beta_flavor sentinel file
next to the EXE instead (Start Menu shortcuts cannot set env vars);
every other install (public AppImage / Flatpak / AUR stable / Windows
stable) leaves both unset. Functions below read both on each call so
tests can flip either with monkeypatch and so the answer is never stale
relative to the running process's environment.
"""

import os
import sys


def _beta_sentinel_path() -> str:
    """Path to the optional Windows beta marker file next to the running EXE.

    The Windows beta installer drops `.beta_flavor` here so the Start Menu
    shortcut (which cannot set env vars) still triggers beta mode. Factored
    out so tests can monkeypatch the path without poking sys.executable.
    """
    try:
        return os.path.join(os.path.dirname(sys.executable), ".beta_flavor")
    except Exception:
        return ""


def is_beta() -> bool:
    if os.environ.get("TTMT_BETA"):
        return True
    path = _beta_sentinel_path()
    return bool(path) and os.path.exists(path)


def config_dir_name() -> str:
    return "toontown_multitool_beta" if is_beta() else "toontown_multitool"


def config_dir() -> str:
    # Test affordance: redirect the config dir under pytest. Not a supported
    # user-facing override.
    override = os.environ.get("TTMT_CONFIG_DIR")
    if override:
        return override
    name = config_dir_name()
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{name}")
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return os.path.join(config_home, name)
    return os.path.expanduser(f"~/.config/{name}")


def bundle_id() -> str:
    """Reverse-DNS macOS bundle identifier, stable forever per channel.
    Matches the Flatpak app-id family (io.github.flossbud.*)."""
    base = "io.github.flossbud.ToonTownMultiTool"
    return f"{base}.beta" if is_beta() else base


def keyring_service() -> str:
    return "ttmt-beta" if is_beta() else "toontown_multitool"


def cc_token_service() -> str:
    """Keyring service name for CC launcher tokens. Channel-aware:
    beta and stable builds get separate token namespaces so a user
    can run both side-by-side without cross-pollution.
    """
    return f"{keyring_service()}_cc_token"


def window_title() -> str:
    return "ToonTown MultiTool BETA" if is_beta() else "ToonTown MultiTool"


def app_name() -> str:
    return "ToonTown MultiTool BETA" if is_beta() else "ToonTown MultiTool"
