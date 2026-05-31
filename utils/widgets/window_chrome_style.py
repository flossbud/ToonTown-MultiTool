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


def header_top_radius_qss(header_bg: str, border_color: str, radius: int,
                          top_rim: str = None) -> str:
    """Header rounds its own top corners (nested 1px inside the card outline at
    radius - STROKE_INSET) and keeps its bottom divider. When `top_rim` is given,
    its `border-top` becomes the window's inner 'lit rim' - it sits 1px inside the
    card's top outline because the header is inset by STROKE_INSET."""
    r = max(0, radius - STROKE_INSET) if radius > 0 else 0
    rim = f"    border-top: 1px solid {top_rim};\n" if top_rim else ""
    return (
        f"QFrame#app_header {{\n"
        f"    background: {header_bg};\n"
        f"{rim}"
        f"    border-bottom: 1px solid {border_color};\n"
        f"    border-top-left-radius: {r}px;\n"
        f"    border-top-right-radius: {r}px;\n"
        f"}}"
    )
