#!/usr/bin/env python3
"""Minimal GUI .app parent for the TCC attribution spike (Phase 0, THROWAWAY).

On launch it spawns the pure-ctypes inject helper (shipped beside it in Resources)
under `/usr/bin/python3 -s` with a SCRUBBED env, passing the target coords from a sidecar
JSON, and logs the helper's provenance + inject result to ~/ttmt_cs_spike_app.log.

Grant THIS app Accessibility (bundle id com.flossbud.ttmt.csspike) on a clean account and
grant Python NOTHING, to learn whether the app grant covers the /usr/bin/python3 child
(INHERIT) or the child needs its own (OWN-GRANT). See
docs/superpowers/macos-clicksync-ctypes-spike-validation.md (Spike B).
"""
import json
import os
import subprocess
import sys
import time

LOG = os.path.expanduser("~/ttmt_cs_spike_app.log")
SIDECAR = os.path.expanduser("~/ttmt_cs_spike_target.json")
SYSTEM_PYTHON = "/usr/bin/python3"
SCRUBBED_ENV = {"PATH": "/usr/bin:/bin"}  # no DYLD_*/PYTHON*; minimal PATH


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{msg}\n")


def _find_helper():
    """Locate the bundled inject helper robustly. PyInstaller may place datas under
    Contents/Resources OR Contents/Frameworks depending on version, so search candidate
    roots rather than assuming one (the spec verifies the actual layout at build time)."""
    name = "macos_clicksync_ctypes_spike.py"
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))  # .../Contents/MacOS
    contents = os.path.dirname(exe_dir)                          # .../Contents
    candidates = [
        getattr(sys, "_MEIPASS", None),
        os.path.join(contents, "Resources"),
        os.path.join(contents, "Frameworks"),
        os.path.dirname(os.path.abspath(__file__)),
    ]
    for root in candidates:
        if root and os.path.exists(os.path.join(root, name)):
            return os.path.join(root, name)
    # last resort: return the _MEIPASS path so the failure log shows where we looked
    return os.path.join(getattr(sys, "_MEIPASS", exe_dir), name)


def run(argv):
    return subprocess.run(argv, env=SCRUBBED_ENV, capture_output=True, text=True)


def main():
    helper = _find_helper()
    log(f"\n===== {time.ctime()} parent_pid={os.getpid()} helper={helper} =====")
    prov = run([SYSTEM_PYTHON, "-s", helper, "provenance"])
    log("PROVENANCE:\n" + prov.stdout + (prov.stderr or ""))

    if not os.path.exists(SIDECAR):
        log(f"NO sidecar at {SIDECAR}; provenance-only run. Drop the target JSON to inject.")
        return
    tgt = json.load(open(SIDECAR))
    argv = [SYSTEM_PYTHON, "-s", helper, "inject",
            "--pid", str(tgt["pid"]), "--wid", str(tgt["wid"]),
            "--win-x", str(tgt["win"][0]), "--win-y", str(tgt["win"][1]),
            "--screen-x", str(tgt["screen"][0]), "--screen-y", str(tgt["screen"][1]),
            "--kind", tgt.get("kind", "click"),
            "--countdown", str(tgt.get("countdown", 5)),
            "--repeat", str(tgt.get("repeat", 1))]
    log("INJECT argv: " + " ".join(argv))
    res = run(argv)
    log("INJECT stdout:\n" + res.stdout)
    log("INJECT stderr:\n" + (res.stderr or ""))
    log(f"INJECT rc={res.returncode}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("PARENT ERROR:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__)))
