"""Resolve a bundled asset from `assets/`, in-repo or frozen.

Single definition site. Replaces the private copies that lived in
tabs/launch_tab.py, tabs/credits_tab.py and utils/widgets/keysets/_assets.py,
so widget packages never import a tab module to find an image.
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
