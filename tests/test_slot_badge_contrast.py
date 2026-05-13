"""Pin: the light-mode slot_dim color must have at least 3:1 contrast
against the light-mode card_toon_bg, so the numbered slot badges don't
disappear on cards. WCAG 1.4.11 (non-text contrast) baseline."""

from utils.theme_manager import get_theme_colors


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    light, dark = max(la, lb), min(la, lb)
    return (light + 0.05) / (dark + 0.05)


def test_light_slot_dim_contrast_against_card_bg_meets_3_to_1():
    c = get_theme_colors(is_dark=False)
    ratio = _contrast(c["slot_dim"], c["card_toon_bg"])
    assert ratio >= 3.0, (
        f"slot_dim {c['slot_dim']!r} on card_toon_bg {c['card_toon_bg']!r} "
        f"only reaches {ratio:.2f}:1; WCAG 1.4.11 requires >= 3:1."
    )
