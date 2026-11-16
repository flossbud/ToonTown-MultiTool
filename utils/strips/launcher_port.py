"""What the compact launcher needs from the app's launcher.

A provider is anything with:

    changed            a Qt signal (no arguments): the list or a state changed
    accounts()         the accounts, in the launcher's own order
    launch(account_id) start that account the way its launcher card does

Each account has the attributes of LaunchAccount; a provider may return
these, or its own objects or dicts with the same names.
"""
from __future__ import annotations

from dataclasses import dataclass

IDLE = "idle"
LAUNCHING = "launching"
RUNNING = "running"


@dataclass(frozen=True)
class LaunchAccount:
    account_id: str
    game: str             # "ttr" | "cc"
    label: str
    state: str = IDLE     # IDLE | LAUNCHING | RUNNING
    toon: str = ""        # the running toon's name, when known


def as_account(item) -> LaunchAccount:
    """A LaunchAccount from whatever a provider returned."""
    if isinstance(item, LaunchAccount):
        return item
    get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
    state = get("state", IDLE)
    return LaunchAccount(
        account_id=str(get("account_id", "")),
        game=str(get("game", "ttr")),
        label=str(get("label", "") or ""),
        state=state if state in (IDLE, LAUNCHING, RUNNING) else IDLE,
        toon=str(get("toon", "") or ""),
    )


def read_accounts(port) -> tuple[LaunchAccount, ...]:
    if port is None:
        return ()
    try:
        return tuple(as_account(a) for a in port.accounts())
    except Exception:
        return ()
