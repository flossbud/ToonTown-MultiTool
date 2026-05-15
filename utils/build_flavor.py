"""Single source of truth for build flavor (stable vs beta).

The Arch ttmt-beta package's launcher sets TTMT_BETA=1 before exec'ing
main.py; every other install (public AppImage / Flatpak / EXE / AUR
stable) leaves it unset. Functions below read the env on each call so
tests can flip the flag with monkeypatch and so the answer is never
stale relative to the running process's environment.
"""

import os


def is_beta() -> bool:
    return bool(os.environ.get("TTMT_BETA"))


def config_dir_name() -> str:
    return "toontown_multitool_beta" if is_beta() else "toontown_multitool"


def config_dir() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return os.path.join(config_home, config_dir_name())
    return os.path.expanduser(f"~/.config/{config_dir_name()}")


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
