"""Pure geometry helpers for the main window chrome. No Qt imports so these
stay trivially unit-testable."""


def clamp_window_height(available_height: int, target: int = 862, margin: int = 48) -> int:
    """Default window height: the target, but never larger than the usable
    screen height minus a margin. On an unknown/zero available height, fall
    back to the target."""
    if available_height <= 0:
        return target
    return min(target, available_height - margin)
