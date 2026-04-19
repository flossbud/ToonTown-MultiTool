from PySide6.QtGui import QPixmap, QPainter, QFont, QColor
from PySide6.QtWidgets import QApplication

_USE_EMOJI = None
_USE_MISC  = None


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


def _misc_supported() -> bool:
    """Test BMP misc/arrow symbols like ↻ that may not be in all fonts."""
    return _can_render("↻")


def S(emoji: str, fallback: str) -> str:
    """Return emoji if the system supports emoji codepoints, else fallback."""
    global _USE_EMOJI
    if _USE_EMOJI is None:
        _USE_EMOJI = _emoji_supported()
    return emoji if _USE_EMOJI else fallback


def M(symbol: str, fallback: str) -> str:
    """Return symbol if misc BMP symbols render, else fallback.
    Use for non-emoji unicode like arrows (↻ ↺ ⟳ etc)."""
    global _USE_MISC
    if _USE_MISC is None:
        _USE_MISC = _misc_supported()
    return symbol if _USE_MISC else fallback