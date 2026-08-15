"""Resolve `assets/<name>` for launcher-adjacent UI call sites.

Shared by launcher, credits, keysets, settings, and account-reorder code so
widget packages use the resolver without importing a tab module.
"""
from __future__ import annotations

import os
import sys

# utils/asset_paths.py -> utils/ -> repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset_path(name: str) -> str:
    """Absolute path to `assets/<name>`. Under PyInstaller the bundle root
    (`sys._MEIPASS`) replaces the repo root."""
    base = getattr(sys, "_MEIPASS", _REPO_ROOT)
    return os.path.join(base, "assets", name)
