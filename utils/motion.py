"""Centralized motion vocabulary for the ToonTown MultiTool UI.

All navigation animations import their durations, easings, and helpers
from here. The is_reduced() gate is the single source of truth for
whether animations should run or snap.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, Qt, QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

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


# Settings keys this module cares about. Used to filter on_change events.
_MOTION_SETTINGS_KEYS = frozenset({"reduce_motion", "reduce_motion_set_explicitly"})


def on_settings_change(key: str, value) -> None:
    """Wire as a SettingsManager.on_change callback so toggling the
    reduce-motion preference invalidates our cache."""
    if key in _MOTION_SETTINGS_KEYS:
        _refresh_cache()


# ── Page transition helper ───────────────────────────────────────────────────

def push_slide_pages(stack, from_idx: int, to_idx: int, axis: str = "h"):
    """Animate the QStackedWidget from from_idx to to_idx.

    axis='h': horizontal push-slide. Direction = sign(to_idx - from_idx).
    axis='v': vertical. Incoming enters from y=-H; outgoing settles +0.08*H
              and fades to opacity 0.

    Uses two QLabel proxies to avoid layout reflow on live page widgets.
    Returns the running QParallelAnimationGroup, or None when reduced motion
    is on (in which case the index is snapped immediately).
    """
    if is_reduced():
        stack.setCurrentIndex(to_idx)
        return None

    # Cancel any in-flight (or pending) transition on this stack.
    pending_timer = getattr(stack, "_in_flight_timer", None)
    if pending_timer is not None:
        pending_timer.stop()
        stack._in_flight_timer = None
    in_flight = getattr(stack, "_in_flight_anim", None)
    if in_flight is not None and in_flight.state() == QAbstractAnimation.Running:
        in_flight.stop()
    if in_flight is not None:
        stack._in_flight_anim = None
    _delete_transition_proxies(stack)

    outgoing = stack.widget(from_idx)
    incoming = stack.widget(to_idx)
    w, h = stack.width(), stack.height()

    # Ensure incoming has been laid out at least once so its grab is non-empty.
    if incoming.size() != stack.size():
        incoming.resize(stack.size())

    out_pix = outgoing.grab()
    in_pix = incoming.grab()

    out_label = _make_proxy(stack, out_pix, w, h)
    in_label = _make_proxy(stack, in_pix, w, h)

    if axis == "h":
        direction = 1 if to_idx > from_idx else -1
        in_start = QPoint(direction * w, 0)
        out_end = QPoint(-direction * w, 0)
        in_end = QPoint(0, 0)
    elif axis == "v":
        in_start = QPoint(0, -h)
        out_end = QPoint(0, int(h * 0.08))
        in_end = QPoint(0, 0)
    else:
        raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")

    out_label.move(0, 0)
    in_label.move(in_start)

    raw_duration = DURATION_PAGE * _TEST_DURATION_SCALE
    duration = 0 if raw_duration == 0.0 else max(1, int(raw_duration))

    group = QParallelAnimationGroup()
    group.addAnimation(_anim_pos(out_label, QPoint(0, 0), out_end, duration))
    group.addAnimation(_anim_pos(in_label, in_start, in_end, duration))

    if axis == "v":
        # Outgoing also fades for the brand-click feel.
        effect = QGraphicsOpacityEffect(out_label)
        out_label.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(duration)
        fade.setEasingCurve(EASE_STANDARD)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        group.addAnimation(fade)

    def _finalize():
        out_label.deleteLater()
        in_label.deleteLater()
        stack.setCurrentIndex(to_idx)
        if getattr(stack, "_in_flight_anim", None) is group:
            stack._in_flight_anim = None
        if getattr(stack, "_in_flight_timer", None) is start_timer:
            stack._in_flight_timer = None

    group.finished.connect(_finalize)
    stack._in_flight_anim = group

    # Defer start() so callers can connect to group.finished before it fires
    # and inspect _in_flight_anim synchronously (interrupt detection).
    start_timer = QTimer()
    start_timer.setSingleShot(True)
    start_timer.timeout.connect(group.start)
    start_timer.start(0)
    stack._in_flight_timer = start_timer

    return group


def _make_proxy(parent, pixmap, w: int, h: int) -> QLabel:
    label = QLabel(parent)
    label.setPixmap(pixmap)
    label.setProperty("is_transition_proxy", True)
    label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    label.resize(w, h)
    label.show()
    label.raise_()
    return label


def _anim_pos(target, start: QPoint, end: QPoint, duration: int) -> QPropertyAnimation:
    anim = QPropertyAnimation(target, b"pos")
    anim.setDuration(duration)
    anim.setEasingCurve(EASE_STANDARD)
    anim.setStartValue(start)
    anim.setEndValue(end)
    return anim


def _delete_transition_proxies(parent) -> None:
    for child in parent.findChildren(QLabel):
        if child.property("is_transition_proxy"):
            child.deleteLater()
