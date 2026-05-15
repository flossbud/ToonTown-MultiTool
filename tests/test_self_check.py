import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_self_check_exits_zero():
    """`python main.py --self-check` must import every module, build the
    main window, and exit 0 on a supported interpreter."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "main.py", "--self-check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"--self-check failed (exit {result.returncode})\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_platform_only_modules_excludes_kwallet_jeepney_off_linux():
    """utils.kwallet_jeepney raises ImportError at import time on non-Linux,
    so the self-check import sweep must skip it on Windows and macOS."""
    from main import _platform_only_modules

    assert "utils.kwallet_jeepney" in _platform_only_modules("win32")
    assert "utils.kwallet_jeepney" in _platform_only_modules("darwin")
    assert "utils.kwallet_jeepney" not in _platform_only_modules("linux")


def test_platform_only_modules_excludes_win32_backend_off_windows():
    """The pre-existing win32_backend exclusion must survive the refactor."""
    from main import _platform_only_modules

    assert "utils.win32_backend" in _platform_only_modules("linux")
    assert "utils.win32_backend" in _platform_only_modules("darwin")
    assert "utils.win32_backend" not in _platform_only_modules("win32")
