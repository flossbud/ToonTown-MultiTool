"""Run subprocesses on the host when packaged as a Flatpak.

When the app is running inside a Flatpak sandbox, host binaries (the game
engines, xdotool, xprop, ss, netstat) are not directly executable from inside
the sandbox. `flatpak-spawn --host CMD ARGS` proxies a command to the host
session bus and runs it outside the sandbox.

Outside Flatpak, the helpers fall through to the original argv unchanged.
"""

import os
import shutil
import subprocess


_FLATPAK_INFO = "/.flatpak-info"


def in_flatpak() -> bool:
    return os.path.exists(_FLATPAK_INFO)


def host_argv(argv):
    """Wrap argv with `flatpak-spawn --host` when running inside Flatpak.

    Pass the host-side env explicitly so DISPLAY, XAUTHORITY, etc. survive.
    """
    if not in_flatpak():
        return list(argv)
    spawn = shutil.which("flatpak-spawn") or "/usr/bin/flatpak-spawn"
    return [spawn, "--host", *argv]


def host_run(argv, **kwargs):
    return subprocess.run(host_argv(argv), **kwargs)


def host_check_output(argv, **kwargs):
    return subprocess.check_output(host_argv(argv), **kwargs)


# Env vars whose values are meaningful only inside the Flatpak sandbox.
# Forwarding these to a host process via flatpak-spawn breaks the host process
# (e.g. XAUTHORITY=/run/flatpak/Xauthority makes X11 auth fail because that
# path does not exist on the host). When omitted, flatpak-portal fills in the
# correct host values.
_SANDBOX_ONLY_ENV = frozenset({
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "XDG_DATA_DIRS",
    "XDG_CONFIG_DIRS",
    "PATH",
    "QT_PLUGIN_PATH",
    "ALSA_CONFIG_PATH",
    "ALSA_CONFIG_DIR",
    "GTK_RC_FILES",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
})


def _is_sandbox_path(value: str) -> bool:
    return value.startswith(("/app/", "/run/flatpak/", "/usr/share/runtime/"))


def host_popen(argv, **kwargs):
    """Popen variant. When sandboxed, pass env via --env=KEY=VAL flags so the
    host process sees the variables (Popen's env= alone only changes the
    sandbox-side environment, which flatpak-spawn does not forward by default).

    Strips env vars whose values are sandbox-internal so the host process
    inherits the correct host defaults from flatpak-portal.
    """
    if not in_flatpak():
        return subprocess.Popen(argv, **kwargs)
    spawn = shutil.which("flatpak-spawn") or "/usr/bin/flatpak-spawn"
    env_flags = []
    env = kwargs.pop("env", None)
    if env is not None:
        for k, v in env.items():
            if v is None:
                continue
            if k in _SANDBOX_ONLY_ENV:
                continue
            if _is_sandbox_path(str(v)):
                continue
            env_flags.append(f"--env={k}={v}")
    cwd = kwargs.pop("cwd", None)
    if cwd:
        env_flags.append(f"--directory={cwd}")
    return subprocess.Popen([spawn, "--host", *env_flags, *argv], **kwargs)
