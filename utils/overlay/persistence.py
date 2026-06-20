"""Persistence + screen-clamp helpers for the transparent-mode overlay group
anchor + scale (Task 6.1).

PURE (no Qt): the controller supplies screen geometry as primitive tuples, so the
clamp logic is unit-testable headless. Stored state (spec section 12): the group
anchor (the emblem-center point in LOGICAL GLOBAL coordinates), the group scale,
and the MONITOR IDENTITY (the screen name) the anchor lived on - so a restore can
recenter when that monitor is gone.
"""
from __future__ import annotations

from utils.overlay.scale import clamp_scale

KEY_ANCHOR = "transparent_group_anchor"
KEY_SCALE = "transparent_group_scale"
KEY_MONITOR = "transparent_group_monitor"


def clamp_anchor_to_screens(anchor, monitor, screens):
    """Return a group anchor guaranteed to land on a currently-visible monitor.

    Parameters
    ----------
    anchor:  ``(cx, cy)`` logical-global emblem-center point (possibly stale).
    monitor: the screen NAME the anchor was saved on (or None).
    screens: list of ``(name, left, top, right, bottom)`` for each connected
             screen (logical coordinates; right/bottom inclusive edges).

    If the saved *monitor* is still present, clamp the anchor within its bounds
    (in case it drifted off-edge). If that monitor is GONE but the anchor still
    lands on SOME screen, keep it. Otherwise recenter on the first screen. With no
    screens at all, return the anchor unchanged.
    """
    by_name = {name: (l, t, r, b) for (name, l, t, r, b) in screens}
    cx, cy = anchor
    if monitor in by_name:
        l, t, r, b = by_name[monitor]
        return (min(max(cx, l), r), min(max(cy, t), b))
    for (name, l, t, r, b) in screens:
        if l <= cx <= r and t <= cy <= b:
            return (cx, cy)
    if screens:
        _name, l, t, r, b = screens[0]
        return ((l + r) // 2, (t + b) // 2)
    return (cx, cy)


def clamp_anchor_to_envelope(anchor, screens, margin):
    """Clamp an emblem-center anchor to the union of screen rects, each inflated
    outward by *margin* px.

    Lets the cluster slide past any edge while keeping the leading slice of the
    emblem on-screen (margin == emblem_size // 4 -> a quarter stays visible).

    anchor:  ``(cx, cy)`` logical-global emblem center.
    screens: list of ``(name, left, top, right, bottom)`` (right/bottom inclusive).
    margin:  px each screen rect is inflated outward by.

    If the anchor lies inside any inflated screen rect, return it unchanged (so
    movement across adjacent monitors and within the margin band is free).
    Otherwise return the nearest point on the union of inflated rects (clamp to
    each, pick the closest by squared distance). With no screens, identity.
    """
    cx, cy = anchor
    if not screens:
        return (cx, cy)
    best = None
    best_d2 = None
    for (_name, l, t, r, b) in screens:
        il, it, ir, ib = l - margin, t - margin, r + margin, b + margin
        if il <= cx <= ir and it <= cy <= ib:
            return (cx, cy)
        qx = min(max(cx, il), ir)
        qy = min(max(cy, it), ib)
        d2 = (qx - cx) ** 2 + (qy - cy) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best = d2, (qx, qy)
    return best


def monitor_for_anchor(anchor, screens):
    """Return the NAME of the screen containing *anchor*, or the first screen's
    name (or None if there are no screens)."""
    cx, cy = anchor
    for (name, l, t, r, b) in screens:
        if l <= cx <= r and t <= cy <= b:
            return name
    return screens[0][0] if screens else None


def load_overlay_state(settings):
    """Read ``(anchor | None, scale, monitor | None)`` from *settings* with
    defaults (anchor None = none saved yet; scale clamped to range)."""
    raw = settings.get(KEY_ANCHOR, None)
    anchor = None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            anchor = (int(raw[0]), int(raw[1]))
        except (TypeError, ValueError):
            anchor = None
    try:
        scale = clamp_scale(float(settings.get(KEY_SCALE, 1.0) or 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    monitor = settings.get(KEY_MONITOR, None)
    return anchor, scale, monitor


def save_overlay_state(settings, anchor, scale, monitor):
    """Persist the group anchor (logical global), scale, and monitor identity."""
    settings.set(KEY_ANCHOR, [int(anchor[0]), int(anchor[1])])
    settings.set(KEY_SCALE, clamp_scale(float(scale)))
    settings.set(KEY_MONITOR, monitor)
