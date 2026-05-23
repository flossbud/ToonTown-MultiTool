from PySide6.QtGui import QPixmap, QPainter, QFont, QColor
from PySide6.QtWidgets import QApplication

_USE_EMOJI = None


def _can_render(char: str) -> bool:
    """Check if a unicode character renders any pixels with the default font."""
    pm = QPixmap(20, 20)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setFont(QFont(QApplication.instance().font().family(), 12))
    p.drawText(pm.rect(), char)
    p.end()
    img = pm.toImage()
    for x in range(20):
        for y in range(20):
            if img.pixel(x, y) != 0:
                return True
    return False


def _emoji_supported() -> bool:
    return _can_render("✅")


def S(emoji: str, fallback: str) -> str:
    """Return emoji if the system supports emoji codepoints, else fallback."""
    global _USE_EMOJI
    if _USE_EMOJI is None:
        _USE_EMOJI = _emoji_supported()
    return emoji if _USE_EMOJI else fallback


_USE_TRIANGLE = None


def _triangle_supported() -> bool:
    """Test that BMP geometric triangles like ▶ render with the current font.
    These are widely supported in basic Unicode fonts (DejaVu, Liberation,
    Noto) so this returns True even on systems where emoji color fonts
    aren't installed."""
    return _can_render("▶")


def M(misc: str, fallback: str) -> str:
    """Return `misc` if the system can render BMP arrow/triangle symbols,
    else `fallback`.

    Unlike `S()`, this does NOT require emoji-codepoint support — it gates
    only on basic BMP geometric shape support (U+25B6 family). Use this for
    chevrons, arrows, and other glyphs that should render even on systems
    without an emoji color font."""
    global _USE_TRIANGLE
    if _USE_TRIANGLE is None:
        _USE_TRIANGLE = _triangle_supported()
    return misc if _USE_TRIANGLE else fallback