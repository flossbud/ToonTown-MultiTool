"""The three faces the Roll Call windows carry, and where their files are.

Each file is its own family (see scripts/build_rollcall_fonts.py), asked for
by its exact name, so no platform gets to pick a neighbouring weight or fake
a bold. The headline face is what makes this read as Toontown: a missing file
is reported once, loudly, and the system face stands in.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QFont, QFontDatabase

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DISPLAY = ("RollcallFredoka-Bold.ttf", "Rollcall Fredoka Bold", 700)
_UI = {
    400: ("RollcallInter-Regular.ttf", "Rollcall Inter Regular"),
    500: ("RollcallInter-Medium.ttf", "Rollcall Inter Medium"),
    600: ("RollcallInter-SemiBold.ttf", "Rollcall Inter SemiBold"),
    700: ("RollcallInter-Bold.ttf", "Rollcall Inter Bold"),
    800: ("RollcallInter-ExtraBold.ttf", "Rollcall Inter ExtraBold"),
}
_MONO = {
    500: ("RollcallMono-Medium.ttf", "Rollcall Mono Medium"),
    700: ("RollcallMono-Bold.ttf", "Rollcall Mono Bold"),
}

_loaded: bool | None = None
_missing: list[str] = []


def asset_path(name: str) -> str:
    """``assets/<name>``; under a frozen build the bundle root stands in for
    the repo root."""
    base = getattr(sys, "_MEIPASS", _REPO_ROOT)
    return os.path.join(base, "assets", name)


def ensure_loaded() -> bool:
    """Register the font files with Qt, once. True when every file loaded."""
    global _loaded
    if _loaded is not None:
        return _loaded
    files = [_DISPLAY[0]] + [f for f, _ in _UI.values()] + [f for f, _ in _MONO.values()]
    for filename in files:
        path = asset_path(os.path.join("fonts", "rollcall", filename))
        if not os.path.exists(path) or QFontDatabase.addApplicationFont(path) < 0:
            _missing.append(filename)
    _loaded = not _missing
    if _missing:
        print(f"[RollCall] fonts missing, system face stands in: {', '.join(_missing)}")
    return _loaded


def missing() -> list[str]:
    ensure_loaded()
    return list(_missing)


def _make(family: str, weight: int, px: float, spacing: float = 0.0) -> QFont:
    ensure_loaded()
    font = QFont(family)
    font.setPixelSize(max(1, round(px)))
    font.setWeight(QFont.Weight(weight))
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setHintingPreference(QFont.PreferNoHinting)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


def display(px: float) -> QFont:
    """Fredoka 700, letter-spacing -0.01em."""
    return _make(_DISPLAY[1], _DISPLAY[2], px, -0.01 * px)


def ui(px: float, weight: int = 400, spacing: float = 0.0) -> QFont:
    """Inter at one of its five shipped weights."""
    _file, family = _UI.get(weight) or _UI[min(_UI, key=lambda w: abs(w - weight))]
    return _make(family, weight, px, spacing)


def mono(px: float, weight: int = 500, spacing: float = 0.0) -> QFont:
    """JetBrains Mono, 500 or 700. Its figures are tabular by design."""
    _file, family = _MONO.get(weight) or _MONO[700 if weight > 600 else 500]
    return _make(family, weight, px, spacing)
