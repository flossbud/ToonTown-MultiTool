"""Modern auto-hide scrollbar — thin pill that fades in on activity.

Used app-wide via install_modern_scrollbar(scroll_area, is_dark=...).
Designed to feel at home alongside the section-block / chip-rail polish.
See docs/superpowers/specs/2026-05-13-modern-scrollbar-design.md.
"""
from __future__ import annotations

from PySide6.QtWidgets import QScrollBar


class AutoHideScrollBar(QScrollBar):
    """A QScrollBar that fades in on activity and fades out at idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
