"""Windows-only elevated relaunch helper. A higher-integrity game blocks our
synthetic input (UIPI); relaunching elevated raises our integrity to match.
os.execv / ShellExecute without the 'runas' verb keep the current integrity, so
elevation specifically requires ShellExecuteEx with verb='runas'."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import NamedTuple

ELEVATION_RESTART_FLAG = "--elevation-restart=uipi"

# Windows starts an elevated process with a fresh environment, so variables
# set for this launch (TTMT_CONFIG_DIR, TTMT_UI_SCALE, the trace switches ...)
# would silently vanish from the elevated copy. They ride along on the command
# line instead, and restore_forwarded_env() puts them back first thing.
ENV_FORWARD_FLAG = "--elevation-env"
_ENV_FORWARD_PREFIX = "TTMT_"
# Decided per process, never handed down.
_ENV_NOT_FORWARDED = {"TTMT_UI_SCALE_ACTIVE"}
_ENV_PARAM_MAX_CHARS = 8000

# The process that started the elevated copy, so the copy can tell its
# predecessor (still exiting, still holding the single-copy lock) from any
# other running copy. See utils/instance_guard.py.
HANDOVER_FLAG = "--handover-from"

# One-shot/internal modes that must NOT be forwarded into the relaunched GUI.
_ONE_SHOT_FLAGS = {"--self-check", "--self-check-keyring", "--apply-installer-config"}
# Flags that consume a following value (so we drop the value too).
_ONE_SHOT_WITH_VALUE = {"--apply-installer-config"}


def build_relaunch_params(argv) -> list:
    """Filter one-shot modes out of argv (argv = sys.argv[1:]) and append the
    elevation-restart flag exactly once. Handles both space-separated
    (`--apply-installer-config PATH`) and equals (`--flag=value`) forms. A
    space-separated value is dropped ONLY when the following token looks like a
    value (not another `-` flag), so an immediately-following unrelated flag is
    never swallowed."""
    out = []
    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        base = tok.split("=", 1)[0]
        if base in (ENV_FORWARD_FLAG, HANDOVER_FLAG):
            i += 1              # a stale copy; the caller adds a fresh one
            continue
        if base in _ONE_SHOT_FLAGS:
            if (base in _ONE_SHOT_WITH_VALUE and "=" not in tok
                    and i + 1 < n and not argv[i + 1].startswith("-")):
                i += 1          # also drop the space-separated value token
            i += 1
            continue
        out.append(tok)
        i += 1
    if ELEVATION_RESTART_FLAG not in out:
        out.append(ELEVATION_RESTART_FLAG)
    return out


def env_forward_param(environ) -> str | None:
    """`--elevation-env=<data>` carrying this process's TTMT_* variables, or
    None when there are none (or far too many to fit a command line)."""
    carried = {k: v for k, v in environ.items()
               if k.upper().startswith(_ENV_FORWARD_PREFIX)
               and k.upper() not in _ENV_NOT_FORWARDED}
    if not carried:
        return None
    data = base64.urlsafe_b64encode(
        json.dumps(carried, sort_keys=True).encode("utf-8")).decode("ascii")
    if len(data) > _ENV_PARAM_MAX_CHARS:
        return None
    return f"{ENV_FORWARD_FLAG}={data}"


def restore_forwarded_env(argv=None, environ=None) -> int:
    """Put back the variables an unelevated parent forwarded, and take the
    flag out of argv. Must run before anything reads a TTMT_* variable.
    Only TTMT_* names are accepted, so the command line cannot be used to set
    anything else. Returns how many variables were restored; never raises."""
    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    restored = 0
    for tok in [t for t in argv[1:] if t.split("=", 1)[0] == ENV_FORWARD_FLAG]:
        argv.remove(tok)
        try:
            carried = json.loads(base64.urlsafe_b64decode(tok.split("=", 1)[1]))
            for key, value in carried.items():
                if (isinstance(key, str) and isinstance(value, str)
                        and key.upper().startswith(_ENV_FORWARD_PREFIX)
                        and key.upper() not in _ENV_NOT_FORWARDED):
                    environ[key] = value
                    restored += 1
        except Exception:
            pass
    return restored


def _relaunch_params(user_argv, environ) -> list:
    """Full parameter list for the elevated copy."""
    _file, prefix = _executable_and_prefix()
    params = prefix + build_relaunch_params(user_argv)
    forwarded = env_forward_param(environ)
    if forwarded:
        params.append(forwarded)
    params.append(f"{HANDOVER_FLAG}={os.getpid()}")
    return params


# ── Elevation at startup ───────────────────────────────────────────────────
#
# Windows drops synthetic input sent to a window of higher integrity, so an
# unelevated MultiTool cannot move a game that is running as administrator.
# Rather than discover that mid-play, ask for administrator access on every
# launch. A manifest that demands it would refuse to start when the prompt is
# declined; asking at runtime lets a declined launch carry on (with the
# warning banner). With consent prompts switched off Windows elevates
# silently, and with UAC off altogether an administrator is already elevated.

NO_ELEVATE_ENV = "TTMT_NO_ELEVATE"
# Helper and one-shot modes: never the interactive app, never prompt.
_NO_PROMPT_FLAGS = _ONE_SHOT_FLAGS | {"--ghost-renderer"}
# The same modes never open a window (the single-copy guard skips them too).
NO_WINDOW_FLAGS = frozenset(_NO_PROMPT_FLAGS)

ELEVATED = "elevated"        # already running as administrator
PROMPT = "prompt"            # decision only: go and ask
RELAUNCHED = "relaunched"    # the elevated copy is starting; this one must exit
DECLINED = "declined"        # asked, and the answer was no (or it failed)
SKIPPED = "skipped"          # did not ask


class StartupElevation(NamedTuple):
    state: str
    reason: str

    def stamp(self) -> str:
        return f"[Elevation] {self.state} ({self.reason})"


_startup_result: StartupElevation | None = None


def decide_startup_elevation(platform, argv, environ,
                             read_integrity, read_elevation_type) -> StartupElevation:
    """Pure decision: should this launch ask for administrator access?
    `argv` is the user argv (sys.argv[1:]). The two readers are only called
    when the answer depends on them."""
    from utils.win32_integrity import (
        SECURITY_MANDATORY_HIGH_RID, SECURITY_MANDATORY_MEDIUM_RID,
        TOKEN_ELEVATION_TYPE_LIMITED,
    )
    if platform != "win32":
        return StartupElevation(SKIPPED, "not Windows")
    for tok in argv:
        if tok.split("=", 1)[0] in _NO_PROMPT_FLAGS:
            return StartupElevation(SKIPPED, f"{tok.split('=', 1)[0]} mode")
    integrity = read_integrity()
    if integrity is None:
        return StartupElevation(SKIPPED, "could not read this process's integrity level")
    if integrity >= SECURITY_MANDATORY_HIGH_RID:
        return StartupElevation(ELEVATED, "running as administrator")
    if integrity < SECURITY_MANDATORY_MEDIUM_RID:
        return StartupElevation(SKIPPED, "sandboxed process cannot elevate")
    if ELEVATION_RESTART_FLAG in argv:
        # We are the relaunched copy and still not elevated. Asking again
        # would loop.
        return StartupElevation(SKIPPED, "already relaunched once and still not administrator")
    if str(environ.get(NO_ELEVATE_ENV, "")).strip().lower() in ("1", "true", "yes", "on"):
        return StartupElevation(SKIPPED, f"{NO_ELEVATE_ENV} is set")
    if read_elevation_type() != TOKEN_ELEVATION_TYPE_LIMITED:
        # A standard account can only elevate with ANOTHER account's password,
        # and the app would then run as that other user, without this user's
        # accounts, keysets and saved logins. Do not push anyone into that.
        return StartupElevation(SKIPPED, "this Windows account is not an administrator")
    return StartupElevation(PROMPT, "not running as administrator")


def elevate_at_startup(argv=None, environ=None, platform=None) -> StartupElevation:
    """Ask for administrator access before anything else starts. Returns a
    RELAUNCHED result when the elevated copy was started (the caller must exit
    at once), otherwise the reason this process carries on as it is. Never
    raises: any failure means "carry on unelevated"."""
    global _startup_result
    from utils import win32_integrity
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    user_argv = list(sys.argv[1:]) if argv is None else list(argv)
    try:
        result = decide_startup_elevation(
            platform, user_argv, environ,
            win32_integrity.own_integrity_level, win32_integrity.own_elevation_type)
        if result.state == PROMPT:
            file, _prefix = _executable_and_prefix()
            params = _relaunch_params(user_argv, environ)
            if _shell_execute_runas(file, params, os.getcwd()):
                result = StartupElevation(RELAUNCHED, "administrator access granted")
            else:
                result = StartupElevation(DECLINED, "administrator prompt was declined")
    except Exception as e:  # noqa: BLE001
        result = StartupElevation(SKIPPED, f"elevation check failed: {e}")
    _startup_result = result
    return result


def startup_prompt_declined() -> bool:
    """True when this launch asked for administrator access and was refused."""
    return _startup_result is not None and _startup_result.state == DECLINED


def _on_success_shutdown():
    """Default success path: quit the Qt app. Imported lazily so the module stays
    import-safe in headless tests."""
    from PySide6.QtWidgets import QApplication
    QApplication.quit()


def _executable_and_prefix():
    """(file, prefix_params) for ShellExecuteEx. Frozen build relaunches the exe
    with no prefix; source/dev relaunches python with main.py as the first
    parameter. The user argv is filtered separately by build_relaunch_params."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    return sys.executable, [os.path.abspath(sys.argv[0])]


def _shell_execute_runas(file, params, cwd) -> bool:
    """Spawn `file` elevated via the runas verb. Returns True on launch, False on
    UAC cancellation (ERROR_CANCELLED) or failure. Windows-only (imported lazily)."""
    try:
        import win32api
        import win32com.shell.shell as shell
        from win32comext.shell import shellcon
        res = shell.ShellExecuteEx(
            nShow=1,
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
            lpVerb="runas",
            lpFile=file,
            lpParameters=subprocess.list2cmdline(params),
            lpDirectory=cwd,
        )
    except Exception:
        return False
    # SEE_MASK_NOCLOSEPROCESS hands us a process handle; we do not wait on the
    # elevated child, so release our handle (this does not terminate it).
    hproc = res.get("hProcess") if res else None
    ok = bool(hproc)
    if hproc:
        try:
            win32api.CloseHandle(hproc)
        except Exception:
            pass
    return ok


def relaunch_elevated(argv=None, on_success_shutdown=None, flush_settings=None) -> bool:
    """Flush settings, then ShellExecuteEx(runas). ONLY on success run the
    shutdown (stop routing + quit). On UAC cancel leave the current app intact.
    Returns True if the elevated instance was launched. `argv` defaults to the
    current process's user argv (sys.argv[1:])."""
    if sys.platform != "win32":
        return False
    if flush_settings is not None:
        try:
            flush_settings()
        except Exception:
            pass
    user_argv = list(sys.argv[1:]) if argv is None else list(argv)
    file, _prefix = _executable_and_prefix()
    params = _relaunch_params(user_argv, os.environ)
    if not _shell_execute_runas(file, params, os.getcwd()):
        return False
    (on_success_shutdown or _on_success_shutdown)()
    return True
