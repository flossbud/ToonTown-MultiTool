"""
Helpers for building a reduced child-process environment for game launches.
"""

import os
import sys


_COMMON_EXACT_VARS = {
    "HOME",
    "PATH",
    "PWD",
    "SHELL",
    "SHLVL",
    "TERM",
    "COLORTERM",
    "LANG",
    "LANGUAGE",
    "TZ",
    "USER",
    "USERNAME",
    "LOGNAME",
    "MAIL",
    "TMP",
    "TEMP",
    "TMPDIR",
}

_COMMON_PREFIXES = (
    "LC_",
)

_POSIX_EXACT_VARS = {
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "DESKTOP_SESSION",
    "SESSION_MANAGER",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_DESKTOP",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "PULSE_SERVER",
    "PIPEWIRE_REMOTE",
}

_POSIX_PREFIXES = (
    "XDG_",
    "QT_",
    "GTK_",
    "GDK_",
    "SDL_",
    "ALSA_",
    "PULSE_",
    "PIPEWIRE_",
    "LIBGL_",
    "__GL_",
    "MESA_",
    "VK_",
    "WINE",
    "DXVK_",
    "VKD3D_",
)

_WINDOWS_EXACT_VARS = {
    "APPDATA",
    "COMSPEC",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PUBLIC",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "USERPROFILE",
    "WINDIR",
}

_WINDOWS_PREFIXES = (
    "QT_",
    "SDL_",
)


def _should_keep_env_var(name: str) -> bool:
    if name in _COMMON_EXACT_VARS:
        return True
    if any(name.startswith(prefix) for prefix in _COMMON_PREFIXES):
        return True

    if sys.platform == "win32":
        if name in _WINDOWS_EXACT_VARS:
            return True
        return any(name.startswith(prefix) for prefix in _WINDOWS_PREFIXES)

    if name in _POSIX_EXACT_VARS:
        return True
    return any(name.startswith(prefix) for prefix in _POSIX_PREFIXES)


def build_launcher_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    Return a reduced child environment suitable for launching local game binaries.

    The allow-list preserves common runtime/session/display variables while
    excluding unrelated shell and developer secrets from the parent environment.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if _should_keep_env_var(name)
    }
    if extra:
        env.update({name: value for name, value in extra.items() if value is not None})
    return env
