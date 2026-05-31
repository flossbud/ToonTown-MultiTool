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
DURATION_PRESS   = 130   # press scale down/up
DURATION_HOVER   = 180   # tint fade, icon morph
DURATION_MENU    = 180   # menu fade + scale (enter)
DURATION_MENU_X  = 120   # menu exit (~67% of enter; exit-faster-than-enter)
DURATION_PILL    = 220   # chip pill slide
DURATION_PAGE    = 280   # page push-slide

# ── Easing tokens ───────────────────────────────────────────────────────
EASE_STANDARD    = QEasingCurve.OutCubic
EASE_PRESS       = QEasingCurve.OutQuad
EASE_MENU_EXIT   = QEasingCurve.InCubic


# ── Scale tokens ────────────────────────────────────────────────────────
PRESS_SCALE = 0.85  # press feedback. Outside the UX 0.95-1.05 band on
                    # purpose: we can only animate the chip's iconSize (the
                    # chip frame itself doesn't scale — QToolButton has no
                    # transform without subclassing paintEvent), so a 4%
                    # shrink in the band is invisible on a 22px icon. 0.85
                    # gives ~3-4 px shrink, which actually reads as feedback.

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


def reduced_motion_enabled() -> bool:
    """Returns True when the OS prefers reduced motion.

    Currently a stub that returns False; the real read (Qt 6.5+
    QStyleHints, Linux gtk-enable-animations, etc.) is deferred
    per the customization-inline-panel spec. The customization
    overlay uses this helper to skip its entry/exit animations
    when the OS prefers reduced motion.
    """
    return False


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

def push_slide_pages(stack, from_idx: int, to_idx: int, axis: str = "h", reverse: bool = False):
    """Animate the QStackedWidget from from_idx to to_idx.

    axis='h': horizontal push-slide. Direction = sign(to_idx - from_idx).
    axis='v': vertical. Incoming enters from y=-H; outgoing settles +0.08*H
              and fades to opacity 0.
              reverse=True: outgoing exits upward (y=-H) and incoming reveals
              from +0.08*H (Credits return).

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

    # Validate axis early before allocating pixmaps and proxies.
    if axis not in ("h", "v"):
        raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")

    outgoing = stack.widget(from_idx)
    incoming = stack.widget(to_idx)
    w, h = stack.width(), stack.height()

    # One-time size sync so QWidget.grab() returns a non-empty pixmap.
    # This runs at most once per page (when the page has never been shown).
    # It does NOT participate in the per-frame animation — proxies handle
    # all motion, so the no-layout-reflow guarantee still holds.
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
        if reverse:
            # Return: outgoing (Credits) slides up off the top; incoming target
            # reveals from a slight downward offset.
            in_start = QPoint(0, int(h * 0.08))
            out_end = QPoint(0, -h)
            in_end = QPoint(0, 0)
        else:
            in_start = QPoint(0, -h)
            out_end = QPoint(0, int(h * 0.08))
            in_end = QPoint(0, 0)

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
        try:
            out_label.deleteLater()
            in_label.deleteLater()
            stack.setCurrentIndex(to_idx)
            if getattr(stack, "_in_flight_anim", None) is group:
                stack._in_flight_anim = None
            if getattr(stack, "_in_flight_timer", None) is start_timer:
                stack._in_flight_timer = None
        except RuntimeError:
            # Stack/labels were already destroyed by Qt cleanup. No work to do.
            return

    group.finished.connect(_finalize)
    stack._in_flight_anim = group

    # Defer start() so callers can connect to group.finished before it fires
    # and inspect _in_flight_anim synchronously (interrupt detection).
    start_timer = QTimer(stack)
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


def pop_menu(popup, anchor, show: bool = True):
    """Animate an OverflowPopup open or closed.

    Open (show=True): popup becomes visible at the anchor's bottom-right,
    opacity 0→1 + scale 0.92→1.0 over DURATION_MENU (OutCubic).
    Close (show=False): opacity 1→0 + scale 1.0→0.92 over DURATION_MENU_X
    (InCubic). Hides the popup on finish.
    """
    if is_reduced():
        if show:
            popup.show_at(anchor)
        else:
            popup.hide()
        return None

    if show:
        popup.show_at(anchor)
        popup.scale = 0.92
        # Opacity via QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect(popup)
        popup.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        duration = max(1, int(DURATION_MENU * _TEST_DURATION_SCALE))
        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(duration)
        fade.setEasingCurve(EASE_STANDARD)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)

        scale = QPropertyAnimation(popup, b"scale")
        scale.setDuration(duration)
        scale.setEasingCurve(EASE_STANDARD)
        scale.setStartValue(0.92)
        scale.setEndValue(1.0)

        group = QParallelAnimationGroup(popup)
        group.addAnimation(fade)
        group.addAnimation(scale)
        group.start()
        popup._motion_anim = group
        return group
    else:
        duration = max(1, int(DURATION_MENU_X * _TEST_DURATION_SCALE))
        effect = popup.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(popup)
            popup.setGraphicsEffect(effect)
            effect.setOpacity(1.0)

        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(duration)
        fade.setEasingCurve(EASE_MENU_EXIT)
        fade.setStartValue(effect.opacity())
        fade.setEndValue(0.0)

        scale = QPropertyAnimation(popup, b"scale")
        scale.setDuration(duration)
        scale.setEasingCurve(EASE_MENU_EXIT)
        scale.setStartValue(popup.scale)
        scale.setEndValue(0.92)

        group = QParallelAnimationGroup(popup)
        group.addAnimation(fade)
        group.addAnimation(scale)
        group.finished.connect(popup.hide)
        group.start()
        popup._motion_anim = group
        return group
