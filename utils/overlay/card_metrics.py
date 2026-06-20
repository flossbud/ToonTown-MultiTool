"""Scale-aware card geometry value object. Pure: no Qt, no PySide6, no heavy deps."""
from __future__ import annotations

from utils.overlay.scale import clamp_scale

# Base card constants (canonical source; mirrors _compact_layout.py).
# All px dimensions are in logical pixels at scale 1.0.
_BASE_PORTRAIT     = 172
_BASE_CARD_RADIUS  = 20
_BASE_CARD_BORDER  = 5
_BASE_CARD_PAD     = 18
_BASE_CARD_MIN_H   = 232
_BASE_GRID_GAP     = 18
_BASE_CUTOUT_R     = 96
_BASE_EMBLEM       = 156
_BASE_CTRL_W       = 158
_BASE_PORTRAIT_RING = 4
# Control-chrome / glow dimensions (Task 1.2b: drive the painted card's
# controls + halo from the same value object).
_BASE_TOGGLE_W     = 34
_BASE_TOGGLE_H     = 36
_BASE_KA_PILL_H    = 38
_BASE_KEYSET_H     = 38
_BASE_KA_DOT       = 28
_BASE_STATUS_TOP_MARGIN = 14
_BASE_GLOW_BLUR    = 22


def _px(base: int | float, scale: float) -> int:
    """Round base * scale to the nearest integer pixel (Python banker's rounding)."""
    return round(base * scale)


class CardMetrics:
    """Immutable card geometry for a given uniform scale factor.

    All pixel-dimension properties (portrait, card_radius, etc.) return ints,
    computed as round(base * scale).  font_pt() returns a float.  icon_px()
    returns round(base * scale) as an int.

    Parameters
    ----------
    scale:
        Desired uniform scale; clamped to [SCALE_MIN, SCALE_MAX] on construction.
    """

    __slots__ = (
        "scale",
        "portrait",
        "card_radius",
        "card_border",
        "card_pad",
        "card_min_h",
        "grid_gap",
        "cutout_r",
        "emblem",
        "ctrl_w",
        "portrait_ring",
        "toggle_w",
        "toggle_h",
        "ka_pill_h",
        "keyset_h",
        "ka_dot",
        "status_top_margin",
        "glow_blur",
    )

    def __init__(self, scale: float = 1.0) -> None:
        s = clamp_scale(scale)
        object.__setattr__(self, "scale", s)
        object.__setattr__(self, "portrait",      _px(_BASE_PORTRAIT,      s))
        object.__setattr__(self, "card_radius",   _px(_BASE_CARD_RADIUS,   s))
        object.__setattr__(self, "card_border",   _px(_BASE_CARD_BORDER,   s))
        object.__setattr__(self, "card_pad",      _px(_BASE_CARD_PAD,      s))
        object.__setattr__(self, "card_min_h",    _px(_BASE_CARD_MIN_H,    s))
        object.__setattr__(self, "grid_gap",      _px(_BASE_GRID_GAP,      s))
        object.__setattr__(self, "cutout_r",      _px(_BASE_CUTOUT_R,      s))
        object.__setattr__(self, "emblem",        _px(_BASE_EMBLEM,        s))
        object.__setattr__(self, "ctrl_w",        _px(_BASE_CTRL_W,        s))
        object.__setattr__(self, "portrait_ring", _px(_BASE_PORTRAIT_RING, s))
        object.__setattr__(self, "toggle_w",      _px(_BASE_TOGGLE_W,      s))
        object.__setattr__(self, "toggle_h",      _px(_BASE_TOGGLE_H,      s))
        object.__setattr__(self, "ka_pill_h",     _px(_BASE_KA_PILL_H,     s))
        object.__setattr__(self, "keyset_h",      _px(_BASE_KEYSET_H,      s))
        object.__setattr__(self, "ka_dot",        _px(_BASE_KA_DOT,        s))
        object.__setattr__(self, "status_top_margin", _px(_BASE_STATUS_TOP_MARGIN, s))
        object.__setattr__(self, "glow_blur",     _px(_BASE_GLOW_BLUR,     s))

    def __setattr__(self, name: str, value: object) -> None:  # type: ignore[override]
        raise AttributeError(f"CardMetrics is read-only; cannot set '{name}'")

    def font_pt(self, base: float) -> float:
        """Return base font size scaled; result is a float (fractional points are valid)."""
        return base * self.scale

    def icon_px(self, base: int | float) -> int:
        """Return base icon dimension scaled and rounded to the nearest pixel (int)."""
        return _px(base, self.scale)

    def __repr__(self) -> str:
        return f"CardMetrics(scale={self.scale})"
