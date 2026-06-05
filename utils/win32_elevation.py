"""Windows-only elevated relaunch helper. A higher-integrity game blocks our
synthetic input (UIPI); relaunching elevated raises our integrity to match.
os.execv / ShellExecute without the 'runas' verb keep the current integrity, so
elevation specifically requires ShellExecuteEx with verb='runas'."""
from __future__ import annotations

import os
import sys

ELEVATION_RESTART_FLAG = "--elevation-restart=uipi"

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


import subprocess


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
    return bool(res and res.get("hProcess"))


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
    file, prefix = _executable_and_prefix()
    params = prefix + build_relaunch_params(user_argv)
    if not _shell_execute_runas(file, params, os.getcwd()):
        return False
    (on_success_shutdown or _on_success_shutdown)()
    return True
