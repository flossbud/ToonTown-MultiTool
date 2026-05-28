"""Run subprocesses on the host when packaged as a Flatpak.

When the app is running inside a Flatpak sandbox, host binaries (the game
engines, xdotool, xprop, ss, netstat) are not directly executable from inside
the sandbox. `flatpak-spawn --host CMD ARGS` proxies a command to the host
session bus and runs it outside the sandbox.

Outside Flatpak, the helpers fall through to the original argv unchanged.
"""

from __future__ import annotations

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


def _clean_host_env() -> dict:
    """Build a copy of os.environ suitable for spawning host commands.

    PyInstaller's --onefile bootloader prepends the bundle's _MEI*
    extraction dir to LD_LIBRARY_PATH so the bundled libs (libpython,
    libstdc++ from the build container, etc.) resolve. Child processes
    inherit that — which BREAKS them when they pull in newer system
    libs that require a newer libstdc++ than the build container's.
    The classic symptom is:

      flatpak: /tmp/_MEI*/libstdc++.so.6: version `GLIBCXX_3.4.30'
        not found (required by /lib/x86_64-linux-gnu/libicuuc.so.74)

    PyInstaller saves the pre-bootloader value in LD_LIBRARY_PATH_ORIG
    so we can restore the original here. If there was no original
    (common on fresh sessions), drop LD_LIBRARY_PATH entirely so the
    system loader uses its defaults.
    """
    env = os.environ.copy()
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def host_run(argv, **kwargs):
    if "env" not in kwargs:
        kwargs["env"] = _clean_host_env()
    return subprocess.run(host_argv(argv), **kwargs)


def host_check_output(argv, **kwargs):
    if "env" not in kwargs:
        kwargs["env"] = _clean_host_env()
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


def host_visible_cache_dir(name: str) -> str:
    """Return a per-user cache directory visible to host-spawned processes."""
    base = os.environ.get("XDG_CACHE_HOME")
    if not base or _is_sandbox_path(base):
        home = os.path.expanduser("~")
        flatpak_id = os.environ.get("FLATPAK_ID")
        if in_flatpak() and flatpak_id:
            base = os.path.join(home, ".var", "app", flatpak_id, "cache")
        else:
            base = os.path.join(home, ".cache")
    path = os.path.join(base, name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def host_visible_xauthority() -> str | None:
    """Copy Flatpak's Xauthority file to a host-visible path.

    The sandbox exposes Xauthority as /run/flatpak/Xauthority, which is not a
    valid path for host processes launched through flatpak-spawn. Copying the
    cookie into the app cache gives host X11 clients a real file to read.
    """
    src = os.environ.get("XAUTHORITY")
    if not src or not os.path.isfile(src):
        return None
    if not in_flatpak() and not _is_sandbox_path(src):
        return src
    try:
        with open(src, "rb") as src_fh:
            data = src_fh.read()
        if not data:
            return None
        dest = os.path.join(host_visible_cache_dir("host-spawn"), "Xauthority")
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as dest_fh:
            dest_fh.write(data)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        return dest
    except OSError:
        return None


def _build_forwarded_env(env, forward_xauthority: bool) -> dict:
    """Return the {KEY: VALUE} subset of `env` that should reach the host child.

    Strips vars whose values are meaningful only inside the sandbox
    (_SANDBOX_ONLY_ENV) and any value that points at a sandbox-internal path,
    so the host process inherits the correct host defaults from flatpak-portal.
    When `forward_xauthority` is `True`, the sandbox Xauthority is replaced
    with a host-visible copy so X11 auth survives the flatpak-spawn boundary.
    """
    forwarded = {}
    if env is None:
        return forwarded
    if forward_xauthority:
        xauthority = host_visible_xauthority()
        if xauthority:
            env = dict(env)
            env["XAUTHORITY"] = xauthority
    for k, v in env.items():
        if v is None:
            continue
        if k in _SANDBOX_ONLY_ENV and not (forward_xauthority and k == "XAUTHORITY"):
            continue
        if _is_sandbox_path(str(v)):
            continue
        forwarded[k] = str(v)
    return forwarded


def _env_block_memfd(forwarded_env: dict) -> int:
    """Serialize forwarded_env to an anonymous in-memory fd in `env -0` format
    (NUL-terminated KEY=VALUE records) and return the fd, seeked to 0.

    Used with `flatpak-spawn --env-fd` so credential values (play cookies,
    tokens) never appear on the host command line in /proc/<pid>/cmdline.
    The caller owns the returned fd and must close it after the spawn.
    """
    block = b"".join(
        f"{k}={v}".encode("utf-8") + b"\0" for k, v in forwarded_env.items()
    )
    fd = os.memfd_create("ttmt-host-env", 0)
    try:
        os.write(fd, block)
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        os.close(fd)
        raise
    return fd


def host_popen(argv, **kwargs):
    """Popen variant. When sandboxed, forward env to the host process through
    flatpak-spawn's --env-fd (an in-memory fd of NUL-separated KEY=VALUE
    records) so credential values never land on the host command line.

    Strips env vars whose values are sandbox-internal so the host process
    inherits the correct host defaults from flatpak-portal.
    """
    forward_xauthority = kwargs.pop("forward_xauthority", False)
    if not in_flatpak():
        return subprocess.Popen(argv, **kwargs)
    spawn = shutil.which("flatpak-spawn") or "/usr/bin/flatpak-spawn"
    env_flags = []
    forwarded_env = _build_forwarded_env(kwargs.pop("env", None), forward_xauthority)
    cwd = kwargs.pop("cwd", None)
    if cwd:
        env_flags.append(f"--directory={cwd}")
    env_fd = None
    if forwarded_env:
        # Pass the env through an in-memory fd rather than --env=KEY=VAL argv
        # flags so credential values never appear in the host process's
        # /proc/<pid>/cmdline. pass_fds keeps the fd at the same number in the
        # flatpak-spawn child (it is not renumbered), which is what --env-fd
        # references. The child gets its own dup across fork, so the parent
        # closes its copy as soon as Popen returns.
        env_fd = _env_block_memfd(forwarded_env)
        env_flags.append(f"--env-fd={env_fd}")
        kwargs["pass_fds"] = tuple(kwargs.get("pass_fds", ())) + (env_fd,)
    try:
        return subprocess.Popen([spawn, "--host", *env_flags, *argv], **kwargs)
    finally:
        if env_fd is not None:
            os.close(env_fd)
