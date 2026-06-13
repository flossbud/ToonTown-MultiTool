"""macOS game-window discovery.

Pure parsing core for filtering a CGWindowListCopyWindowInfo-shaped list
(list of dicts with string keys) down to game windows. PyObjC imports that
actually query the window server are lazy and added in a later task, so this
module imports cleanly on any platform.
"""

from __future__ import annotations

import dataclasses

# Owner-name startswith markers mapped to a game tag. Window titles are NOT
# used for matching because reading them may require Screen Recording
# permission; owner (application) names are available without it.
_GAME_MARKERS = (
    ("Toontown Rewritten", "ttr"),
    ("Corporate Clash", "cc"),
)


@dataclasses.dataclass(frozen=True)
class GameWindow:
    pid: int
    window_id: int
    game: str
    owner: str
    bounds: tuple  # (x, y, w, h)
    bundle_id: str | None = None


def identify_game_windows(window_info) -> list:
    """Filter a CGWindowListCopyWindowInfo-shaped list down to game windows."""
    games = []
    for entry in window_info:
        owner = entry.get("kCGWindowOwnerName", "")
        game = next(
            (tag for marker, tag in _GAME_MARKERS if owner.startswith(marker)),
            None,
        )
        if game is None:
            continue

        pid = entry.get("kCGWindowOwnerPID")
        number = entry.get("kCGWindowNumber")
        if pid is None or number is None:
            continue

        bounds = entry.get("kCGWindowBounds", {})
        x = bounds.get("X", 0)
        y = bounds.get("Y", 0)
        width = bounds.get("Width", 0)
        height = bounds.get("Height", 0)
        if width <= 0 or height <= 0:
            continue

        games.append(
            GameWindow(
                pid=int(pid),
                window_id=int(number),
                game=game,
                owner=owner,
                bounds=(int(x), int(y), int(width), int(height)),
            )
        )
    return games
