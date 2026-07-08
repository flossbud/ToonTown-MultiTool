"""Resolve a bundled asset (repo root / PyInstaller _MEIPASS). Mirrors
tabs/launch_tab.py::_asset_path so keysets does not import a tab module."""
import os
import sys


def asset_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.dirname(os.path.abspath(__file__))))))
    return os.path.join(base, "assets", name)
