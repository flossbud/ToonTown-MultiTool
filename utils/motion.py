"""Centralized motion vocabulary for the ToonTown MultiTool UI.

All navigation animations import their durations, easings, and helpers
from here. The is_reduced() gate is the single source of truth for
whether animations should run or snap.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Optional

from PySide6.QtCore import QEasingCurve

# ── Duration tokens (ms) ────────────────────────────────────────────────
DURATION_PRESS   = 100   # press scale down/up
DURATION_HOVER   = 180   # tint fade, icon morph
DURATION_MENU    = 180   # menu fade + scale (enter)
DURATION_MENU_X  = 120   # menu exit (~67% of enter; exit-faster-than-enter)
DURATION_PILL    = 220   # chip pill slide
DURATION_PAGE    = 280   # page push-slide

# ── Easing tokens ───────────────────────────────────────────────────────
EASE_STANDARD    = QEasingCurve.OutCubic
EASE_PRESS       = QEasingCurve.OutQuad
EASE_MENU_EXIT   = QEasingCurve.InCubic


def ease_overshoot(overshoot: float = 0.10) -> QEasingCurve:
    """OutBack with a configurable overshoot magnitude.

    Qt's OutBack defaults to ~1.7 — way too pronounced for the
    'Toon-tasteful' personality. Default 0.10 gives a barely-perceptible
    settle-bounce on pill width arrival.
    """
    curve = QEasingCurve(QEasingCurve.OutBack)
    curve.setOvershoot(overshoot)
    return curve


# ── Scale tokens ────────────────────────────────────────────────────────
PRESS_SCALE = 0.96  # within the UX 0.95-1.05 scale-feedback band

# ── Test-only override ──────────────────────────────────────────────────
# Tests set this to 0.0 to make non-reduced-motion animations resolve
# in one event-loop tick without hitting the is_reduced() snap path.
_TEST_DURATION_SCALE = 1.0


# ── Reduced-motion gate ─────────────────────────────────────────────────
# Settings manager is injected at app startup; tests stub it directly.
_settings = None  # type: Optional[object]

_OS_REDUCED_MOTION_CACHE: Optional[bool] = None


def set_settings_manager(settings_manager) -> None:
    """Called once at app startup from main.py."""
    global _settings
    _settings = settings_manager


def is_reduced() -> bool:
    """True when animations should snap instead of interpolate.

    Precedence:
      1. If user has explicitly set reduce_motion, that wins.
      2. Otherwise, fall back to OS preference.
    """
    if _settings is not None and _settings.get("reduce_motion_set_explicitly", False):
        return bool(_settings.get("reduce_motion", False))
    return _os_reduced_motion()


def _refresh_cache() -> None:
    """Clear the OS reduced-motion cache. Called when the user toggles
    the setting (so the new value is picked up immediately)."""
    global _OS_REDUCED_MOTION_CACHE
    _OS_REDUCED_MOTION_CACHE = None


def _os_reduced_motion() -> bool:
    """Cached per app session."""
    global _OS_REDUCED_MOTION_CACHE
    if _OS_REDUCED_MOTION_CACHE is None:
        try:
            _OS_REDUCED_MOTION_CACHE = _os_reduced_motion_impl()
        except Exception:
            _OS_REDUCED_MOTION_CACHE = False
    return _OS_REDUCED_MOTION_CACHE


def _os_reduced_motion_impl() -> bool:
    """Platform-specific. Returns False on unknown platforms or errors."""
    system = platform.system()

    if system == "Linux":
        # GNOME
        if shutil.which("gsettings"):
            try:
                out = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
                    capture_output=True, text=True, timeout=2,
                )
                if out.returncode == 0:
                    return out.stdout.strip().lower() == "false"
            except Exception:
                pass
        # KDE
        if shutil.which("kreadconfig5"):
            try:
                out = subprocess.run(
                    ["kreadconfig5", "--file", "kdeglobals", "--group", "KDE",
                     "--key", "AnimationDurationFactor"],
                    capture_output=True, text=True, timeout=2,
                )
                if out.returncode == 0:
                    val = out.stdout.strip()
                    if val:
                        return float(val) == 0.0
            except Exception:
                pass
        return False

    if system == "Windows":
        try:
            import ctypes
            SPI_GETCLIENTAREAANIMATION = 0x1042
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0,
            ):
                return enabled.value == 0
        except Exception:
            pass
        return False

    # macOS and unknown: assume animations on.
    return False
