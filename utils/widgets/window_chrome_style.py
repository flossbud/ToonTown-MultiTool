# utils/widgets/window_chrome_style.py
"""Pure styling helpers for the frameless window chrome: traffic-light colors,
control-glyph sizing, and the QSS strings for the rounded card + header.

Kept free of widget state so it unit-tests without a live window. The window
rounding uses translucency + QSS border-radius (anti-aliased, no custom
paintEvent - see the design spec); these helpers build those QSS strings."""

# PEP 604 unions ("str | None") in the annotations below are evaluated at
# runtime on Python 3.9, which the frozen Linux build still bundles; deferring
# annotations keeps them as strings so module import never touches the union.
from __future__ import annotations

# Geometry constants (px). The bottom inset keeps tab content out of the
# physical bottom corners so the card's rounded background fills them; the
# stroke inset keeps the 1px card border from being overpainted by children.
RADIUS_NORMAL = 16
RADIUS_MAXIMIZED = 0
BOTTOM_INSET = 16
STROKE_INSET = 1
DOT_DIAMETER = 16  # control-button visual dot (was 14)

# Classic traffic-light scheme: (dot color, glyph tint). Glyph is a darker
# shade of the dot so it reads as a subtle mark, not stark white.
TRAFFIC = {
    "min":   ("#febc2e", "#7a4e00"),
    "max":   ("#28c840", "#0c5a1e"),
    "close": ("#ff5f56", "#7a1410"),
}


def glyph_pixel_size(diameter: int) -> int:
    """Glyph size that scales with the dot, floored at the old 9px."""
    return max(9, round(diameter * 0.68))


def is_dark_bg(hex_color: str) -> bool:
    """True if the background hex is dark (relative luminance < 0.5).

    Expects a 6-digit hex (`#rrggbb` or `rrggbb`); raises ValueError otherwise
    so a malformed theme color fails fast with a clear message rather than a
    cryptic int-parse error deep in the styling path."""
    h = hex_color[1:] if hex_color.startswith("#") else hex_color
    if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
        raise ValueError(f"is_dark_bg expects a 6-digit hex color, got: {hex_color!r}")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return lum < 0.5


def window_edge_colors(bg_hex: str) -> dict:
    """Edge tokens for the frameless window, chosen by background luminance:
    `outline` = a consistent 1px boundary on all four card edges; `rim` = a 1px
    inner top highlight ("light from above") carried by the header's border-top.
    Designed for both themes (the light rim is faint by design - the slate
    outline does the real window-definition work)."""
    if is_dark_bg(bg_hex):
        return {"outline": "rgba(255,255,255,0.14)", "rim": "rgba(255,255,255,0.10)"}
    return {"outline": "rgba(15,23,42,0.16)", "rim": "rgba(255,255,255,0.55)"}


def card_qss(object_name: str, bg: str, radius: int, outline) -> str:
    """QSS for the root 'card'. With radius>0 AND an outline color, draws the
    rounded background + a uniform 1px outline on all edges. Otherwise a plain
    background (square / native-title-bar path)."""
    if radius > 0 and outline:
        return (
            f"QWidget#{object_name} {{\n"
            f"    background: {bg};\n"
            f"    border-radius: {radius}px;\n"
            f"    border: 1px solid {outline};\n"
            f"}}"
        )
    return f"QWidget#{object_name} {{ background: {bg}; }}"


def header_top_radius_qss(header_bg: str, border_color: str | None, radius: int,
                          top_rim: str = None) -> str:
    """Header rounds its own top corners (nested 1px inside the card outline at
    radius - STROKE_INSET). When `border_color` is falsy the header draws NO
    bottom divider - the nav band below it owns the single hairline, so the
    header and dock read as one continuous surface. When `top_rim` is given, its
    `border-top` becomes the window's inner 'lit rim' - it sits 1px inside the
    card's top outline because the header is inset by STROKE_INSET."""
    r = max(0, radius - STROKE_INSET) if radius > 0 else 0
    rim = f"    border-top: 1px solid {top_rim};\n" if top_rim else ""
    bottom = f"    border-bottom: 1px solid {border_color};\n" if border_color else ""
    return (
        f"QFrame#app_header {{\n"
        f"    background: {header_bg};\n"
        f"{rim}"
        f"{bottom}"
        f"    border-top-left-radius: {r}px;\n"
        f"    border-top-right-radius: {r}px;\n"
        f"}}"
    )


# --- hover/press animation targets + inactive-state colors (pure) ---
HOVER_SCALE = 1.10
PRESS_SCALE = 0.94
HOVER_BRIGHTNESS = 1.18
PRESS_BRIGHTNESS = 0.85


def hover_targets(pressed: bool, hovered: bool):
    """(dot_scale, brightness) for the current interaction state. Press wins."""
    if pressed:
        return (PRESS_SCALE, PRESS_BRIGHTNESS)
    if hovered:
        return (HOVER_SCALE, HOVER_BRIGHTNESS)
    return (1.0, 1.0)


def brighten(hex_color: str, factor: float) -> str:
    """Adjust a #rrggbb color: factor>1 blends toward white by (factor-1),
    factor<1 multiplies channels down (darken). Returns #rrggbb, clamped."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if factor < 1.0:
        r, g, b = (r * factor, g * factor, b * factor)
    elif factor > 1.0:
        t = min(1.0, factor - 1.0)
        r, g, b = (r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t)
    cl = lambda v: max(0, min(255, int(round(v))))
    return "#%02x%02x%02x" % (cl(r), cl(g), cl(b))


def inactive_grey(bg_is_dark: bool):
    """(dot_color, glyph_color) for the unfocused-window dimmed state."""
    if bg_is_dark:
        return ("#5a5d63", "#33353a")
    return ("#b8bcc2", "#8b9098")
