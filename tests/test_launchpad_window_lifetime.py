"""A shut-down launchpad window is freed: nothing it built outlives it.

Runs scripts/launchpad_lifetime_probe.py in a clean process: it builds and
disposes three windows and fails if any window wrapper survives or Qt's
widget count grows (each surviving window used to keep about 30 MB)."""
import os
import subprocess
import sys


def test_disposed_windows_are_freed():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        [sys.executable, os.path.join(repo, "scripts", "launchpad_lifetime_probe.py"), "3"],
        cwd=repo, capture_output=True, text=True, timeout=300,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    summary = [l for l in out.stdout.splitlines()
               if l.startswith(("window ", "leftover", "OK", "LEAK"))]
    assert out.returncode == 0, "\n".join(summary) + out.stderr[-1500:]
    assert summary[-1] == "OK"
