# utils/widgets/window_chrome_style.py
"""Pure styling helpers for the frameless window chrome: traffic-light colors,
control-glyph sizing, and the QSS strings for the rounded card + header.

Kept free of widget state so it unit-tests without a live window. The window
rounding uses translucency + QSS border-radius (anti-aliased, no custom
paintEvent - see the design spec); these helpers build those QSS strings."""

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
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"is_dark_bg expects a 6-digit hex color, got: {hex_color!r}")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return lum < 0.5


def bevel_border_colors(bg_hex: str) -> dict:
    """Top-lighter / bottom-darker 1px bevel stroke colors, chosen by the
    background's luminance so the edge reads on both dark and light themes."""
    if is_dark_bg(bg_hex):
        return {
            "top":    "rgba(255,255,255,0.16)",
            "side":   "rgba(255,255,255,0.10)",
            "bottom": "rgba(255,255,255,0.05)",
        }
    return {
        "top":    "rgba(0,0,0,0.06)",
        "side":   "rgba(0,0,0,0.12)",
        "bottom": "rgba(0,0,0,0.18)",
    }


def card_qss(object_name: str, bg: str, radius: int, colors) -> str:
    """QSS for the root 'card'. When radius>0 and colors are given, draws the
    rounded background + 1px per-side bevel stroke. Otherwise a plain bg
    (native-title-bar / maximized path)."""
    if radius > 0 and colors:
        return (
            f"QWidget#{object_name} {{\n"
            f"    background: {bg};\n"
            f"    border-radius: {radius}px;\n"
            f"    border-top: 1px solid {colors['top']};\n"
            f"    border-left: 1px solid {colors['side']};\n"
            f"    border-right: 1px solid {colors['side']};\n"
            f"    border-bottom: 1px solid {colors['bottom']};\n"
            f"}}"
        )
    return f"QWidget#{object_name} {{ background: {bg}; }}"


def header_top_radius_qss(header_bg: str, border_color: str, radius: int) -> str:
    """Header rounds its own top corners, nested inside the card's 1px stroke
    (radius - STROKE_INSET) so there is no fringe. Keeps its bottom divider."""
    r = max(0, radius - STROKE_INSET) if radius > 0 else 0
    return (
        f"QFrame#app_header {{\n"
        f"    background: {header_bg};\n"
        f"    border-bottom: 1px solid {border_color};\n"
        f"    border-top-left-radius: {r}px;\n"
        f"    border-top-right-radius: {r}px;\n"
        f"}}"
    )
