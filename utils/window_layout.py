"""Pure geometry helpers for the main window chrome. No Qt imports so these
stay trivially unit-testable."""


def clamp_window_height(available_height: int, target: int = 862, margin: int = 48) -> int:
    """Default window height: the target, but never larger than the usable
    screen height minus a margin. On an unknown/zero available height, fall
    back to the target. On a tiny screen (<= margin), use the full available
    height rather than going zero/negative."""
    if available_height <= 0:
        return target
    if available_height <= margin:
        return available_height
    return min(target, available_height - margin)


def compute_logo_size(
    header_width: int,
    asset_w: int,
    asset_h: int,
    target_height: int = 80,
    controls_cluster_width: int = 58,
    side_margin: int = 16,
) -> tuple[int, int]:
    """Return (width, height) for the logo. Scales the asset to target_height
    by aspect ratio, then clamps to a max width that reserves symmetric space
    on both sides for the control cluster so a centered logo never collides.

    controls_cluster_width default 58 = 3*14px dots + 2*8px gaps.
    side_reserve = controls_cluster_width + side_margin (per side).
    Returns (0, 0) when the header is too narrow to safely show the logo.
    Raises ValueError on non-positive asset dimensions (bad/missing pixmap).
    """
    if asset_w <= 0 or asset_h <= 0:
        raise ValueError(f"asset dimensions must be positive, got {asset_w}x{asset_h}")
    aspect = asset_w / asset_h
    side_reserve = controls_cluster_width + side_margin
    max_logo_width = header_width - 2 * side_reserve
    if max_logo_width <= 0:
        return 0, 0
    width = round(target_height * aspect)
    height = target_height
    if width > max_logo_width:
        width = max_logo_width
        height = round(width / aspect)
    return width, height
