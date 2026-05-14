"""Reusable Qt widget subclasses used across the app."""
from utils.widgets.auto_hide_scrollbar import (
    AutoHideScrollBar,
    install_modern_scrollbar,
)

__all__ = ["AutoHideScrollBar", "install_modern_scrollbar"]
