"""Cross-platform import-safety guard for the macOS modules.

Every macOS module must import cleanly on a non-macOS interpreter: all PyObjC /
AppKit / Quartz / objc imports are LAZY (inside functions), so the modules load
on Linux/Windows CI where PyObjC is absent.

A plain `import` on the dev venv (which HAS PyObjC) would be vacuous, so this
runs a FRESH subprocess with every PyObjC top-level module shadowed to None
(making any module-level `import Quartz`/`import objc`/`from AppKit import ...`
raise). If a macOS module imported PyObjC at load time, the subprocess would
fail; success proves the lazy contract holds.
"""
import os
import subprocess
import sys

_MACOS_MODULES = (
    "utils.macos_keycodes",
    "utils.macos_discovery",
    "utils.macos_backend",
    "utils.macos_movement_grabber",
    "utils.macos_ttr_ports",
    "utils.platform_qt",
)

# The repo root (this file lives in <root>/tests/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SUBPROCESS_CODE = """
import sys, importlib

# Shadow every PyObjC top-level module so a module-level import would raise.
_PYOBJC = ("objc", "Quartz", "AppKit", "Foundation", "CoreGraphics", "Cocoa")
for _m in _PYOBJC:
    sys.modules[_m] = None

# Control: confirm the shadowing is actually ACTIVE -- the None sentinel must be
# set for every PyObjC module. This proves the simulation is real on ANY host,
# including Linux CI where PyObjC is naturally absent (so a bare `import Quartz`
# would raise regardless and could NOT prove shadowing on its own).
for _m in _PYOBJC:
    if sys.modules.get(_m, "MISSING") is not None:
        print("CONTROL_FAILED: shadow sentinel not set for " + _m)
        sys.exit(2)
try:
    import Quartz  # noqa: F401
except ImportError:
    pass
else:
    print("CONTROL_FAILED: Quartz import did not raise under shadowing")
    sys.exit(2)

for _name in {modules!r}:
    importlib.import_module(_name)

print("IMPORT_OK")
"""


def test_macos_modules_import_without_pyobjc():
    code = _SUBPROCESS_CODE.format(modules=list(_MACOS_MODULES))
    env = dict(os.environ)
    env["TTMT_NO_VENV_REEXEC"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, (
        f"macOS modules failed to import with PyObjC shadowed:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "IMPORT_OK" in result.stdout, result.stdout
