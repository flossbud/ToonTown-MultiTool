"""What one strip shows. A plain value: the widget paints it and nothing else."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from PySide6.QtGui import QPixmap


@dataclass(frozen=True)
class StripModel:
    name: str = ""
    accent: str = "#4a8fe7"
    game: str = "ttr"
    species: str | None = None          # silhouette fallback for the portrait
    portrait: QPixmap | None = field(default=None, compare=False)
    # The saved framing of that portrait: zoom, offset x, offset y (fractions
    # of the circle), rotation in degrees.
    portrait_frame: tuple = (1.0, 0.0, 0.0, 0.0)
    enabled: bool = True
    running: bool = True                # broadcast service; stopped dims like disabled
    keep_alive: bool | None = True      # None: feature off app-wide, block omitted
    click_sync: bool | None = True      # None: feature off or unsupported, block omitted
    click_sync_state: str = ""          # session's off | armed | active | error
    click_sync_error: str = ""          # why, when the state is "error"
    keysets: tuple[int, ...] = (1, 2, 3)   # visible keyset numbers, ascending
    active: int = 1
    show_add: bool = True               # False at the maximum with none hidden
    hidden_sets: bool = False           # dot on the + when sets are hidden
    home: bool = False                  # toon 1's strip carries the home block
    home_open: bool = False

    @property
    def click_sync_lit(self) -> bool:
        """Lit while on and working. On but in error is drawn unlit with a
        warning dot."""
        return bool(self.click_sync) and self.click_sync_state != "error"

    @property
    def click_sync_failed(self) -> bool:
        return bool(self.click_sync) and self.click_sync_state == "error"

    @property
    def dimmed(self) -> bool:
        """Identity, tools and keysets dim; Enable never does."""
        return not (self.enabled and self.running)

    def with_(self, **changes) -> "StripModel":
        return replace(self, **changes)
