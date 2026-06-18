"""Pure helpers for the window-state restyle guard. _apply_window_corner_state
reapplies an unprefixed `QWidget{}` cascade (full-tree restyle); it only needs
to run when one of these inputs changes."""
from __future__ import annotations


def corner_state_signature(maximized: bool, native_titlebar: bool, theme_key) -> tuple:
    """Everything the corner-state stylesheet depends on. theme_key must change
    whenever the palette does (so a theme switch busts the guard)."""
    rounded = (not native_titlebar) and (not maximized)
    return (rounded, theme_key)


def should_skip_restyle(prev_sig, new_sig, force: bool) -> bool:
    """True when the restyle can be skipped (no visible change). force=True
    (theme/dark-light change) always restyles."""
    if force:
        return False
    return prev_sig is not None and prev_sig == new_sig
