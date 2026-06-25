"""Account-ring view model for the emblem radial menu's Accounts sub-ring.

Qt-free. The ring INCLUDES running accounts with a ``running`` flag (the portrait
shows a status dot and a click is a no-op/focus), and attaches the account's last
in-world toon (name + dna) or marks it a placeholder when none was ever captured.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RingAccount:
    account_id: str
    game: str
    label: str
    toon_name: str | None
    dna: str
    running: bool

    @property
    def is_placeholder(self) -> bool:
        return not self.toon_name


def build_account_ring(ordered_ids, account_for, toon_for, is_running, limit=8):
    """Build the ordered list of ring accounts (most-recent first, capped).

    - ``ordered_ids``: account IDs, most-recent-first (RecentLaunchesStore).
    - ``account_for(aid)``: ``(game, label) | None`` (None => deleted).
    - ``toon_for(aid)``: ``(toon_name, dna) | None`` (None => placeholder).
    - ``is_running(game, aid)``: True if a launcher for the account is running.
    """
    out: list[RingAccount] = []
    for aid in ordered_ids:
        if len(out) >= limit:
            break
        view = account_for(aid)
        if view is None:
            continue
        game, label = view
        toon = toon_for(aid)
        toon_name, dna = (toon if toon else (None, ""))
        out.append(RingAccount(
            account_id=aid, game=game, label=label,
            toon_name=toon_name, dna=dna or "",
            running=is_running(game, aid),
        ))
    return out
