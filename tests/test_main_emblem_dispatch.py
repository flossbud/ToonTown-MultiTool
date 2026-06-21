"""Dispatch logic for the emblem launch menu (the running guard + nav routing),
tested on MultiToonTool._dispatch_emblem_menu_action via a fake `self` so no full
window is constructed.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \\
      PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \\
      ./venv/bin/python -m pytest tests/test_main_emblem_dispatch.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from types import SimpleNamespace
from main import MultiToonTool


def _fake_self():
    calls = {"leave": [], "nav": [], "launch": []}
    launch_tab = SimpleNamespace(
        is_account_running=lambda g, a: a == "running-acct",
        launch_account=lambda g, a: calls["launch"].append((g, a)),
    )
    controller = SimpleNamespace(leave=lambda: calls["leave"].append(1))
    fake = SimpleNamespace(
        launch_tab=launch_tab,
        _mode_controller=controller,
        nav_select=lambda i: calls["nav"].append(i),
    )
    return fake, calls


def test_dispatch_launch_calls_launch_account():
    fake, calls = _fake_self()
    MultiToonTool._dispatch_emblem_menu_action(fake, ("ttr", "a"))
    assert calls["launch"] == [("ttr", "a")]
    assert calls["leave"] == [] and calls["nav"] == []


def test_dispatch_skips_running_account():
    fake, calls = _fake_self()
    MultiToonTool._dispatch_emblem_menu_action(fake, ("ttr", "running-acct"))
    assert calls["launch"] == []          # running guard: never stops a running game


def test_dispatch_nav_leaves_and_navigates():
    fake, calls = _fake_self()
    MultiToonTool._dispatch_emblem_menu_action(fake, ("__nav__", None))
    assert calls["leave"] == [1] and calls["nav"] == [1]
    assert calls["launch"] == []
