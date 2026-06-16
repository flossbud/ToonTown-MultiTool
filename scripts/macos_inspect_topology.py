"""Machine-checkable topology gate for the framework spike. Run BEFORE each human
test: the human result only counts if the artifact topology matches the claim.

Checks: the bootloader/python binary arch (file), the load commands (otool -L) for
a leaked /Library/Frameworks dependency, the presence of Python.framework inside
the bundle, and whether the running slice was genuinely translated by Rosetta
(sysctl.proc_translated). Pure parsers (analyze_*) are unit-tested; the os-calling
wrappers are operator-run.
"""
from __future__ import annotations

import subprocess
import sys


def analyze_otool(otool_output: str) -> dict:
    """Parse `otool -L` text. Flags any ABSOLUTE /Library/Frameworks dependency
    (a relocatability leak) and confirms an @rpath Python reference is present."""
    global_refs, has_rpath_python = [], False
    for raw in otool_output.splitlines():
        line = raw.strip()
        path = line.split(" (", 1)[0].strip()
        if path.startswith("/Library/Frameworks/"):
            global_refs.append(path)
        if path.startswith("@rpath/") and "Python" in path:
            has_rpath_python = True
    return {"global_framework_refs": global_refs, "has_rpath_python": has_rpath_python}


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def inspect_app(app_path: str) -> int:
    """Operator entry: print the topology facts for a built .app. Returns nonzero
    if a /Library/Frameworks leak is found."""
    boot = f"{app_path}/Contents/MacOS/FrameworkSpike"
    print(f"== file: {boot}\n{_run(['file', boot])}", end="")
    findings = analyze_otool(_run(["otool", "-L", boot]))
    print(f"== otool global /Library/Frameworks refs: {findings['global_framework_refs']}")
    print(f"== @rpath Python present: {findings['has_rpath_python']}")
    fw = _run(["find", f"{app_path}/Contents/Frameworks", "-maxdepth", "1",
               "-name", "Python.framework"])
    print(f"== Python.framework in bundle: {bool(fw.strip())} ({fw.strip() or 'absent'})")
    print(f"== sysctl.proc_translated (1 = Rosetta): "
          f"{_run(['sysctl', '-n', 'sysctl.proc_translated']).strip()}")
    return 1 if findings["global_framework_refs"] else 0


if __name__ == "__main__":
    sys.exit(inspect_app(sys.argv[1]))
