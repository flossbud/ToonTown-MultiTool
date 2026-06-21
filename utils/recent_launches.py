"""Recent-launch MRU + menu-model logic for the emblem right-click launch menu.

Qt-free and unit-testable. The store persists an ordered list of account IDs
(front = most recent). The pure functions decide what the right-click menu shows;
all display + eligibility data is resolved fresh at build time because it is
volatile (keyring lock state, running state, renamed labels, deleted accounts).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class RecentLaunchesStore:
    """Ordered MRU of account IDs, persisted via a settings_manager.

    ``settings_manager`` must expose ``get(key, default)`` and ``set(key, value)``;
    pass ``None`` to degrade to a no-op (no persistence, always empty).
    """

    _KEY = "recent_launches"
    _CAP = 10

    def __init__(self, settings_manager):
        self._sm = settings_manager

    def ordered_ids(self) -> list[str]:
        if self._sm is None:
            return []
        raw = self._sm.get(self._KEY, [])
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, str)]

    def record(self, account_id: str) -> None:
        # Type-check first so a non-string never reaches the truthiness test.
        if not isinstance(account_id, str) or not account_id:
            return
        ids = [x for x in self.ordered_ids() if x != account_id]
        ids.insert(0, account_id)
        ids = ids[:self._CAP]
        if self._sm is not None:
            self._sm.set(self._KEY, ids)


@dataclass(frozen=True)
class MenuItem:
    account_id: str
    game: str          # "ttr" | "cc"
    display_label: str


@dataclass(frozen=True)
class RecentMenuModel:
    # A true value object: frozen + a tuple of items, so it cannot be mutated
    # into an inconsistent state after construction.
    items: tuple[MenuItem, ...]
    mixed_games: bool
    status: Literal["ok", "empty", "keyring_locked"]


def resolve_account_view(cred, idx) -> tuple[str, str, bool] | None:
    """Resolve account at global index ``idx`` to ``(game, display_label,
    launchable)`` or ``None`` (deleted / missing username).

    ``cred`` is a CredentialsManager-like object with ``get_account_metadata(idx)``
    (game, username, label, and CC ``launcher_token``) and ``get_account(idx)``
    (password). Launchable mirrors the launch rule: TTR needs a password; CC needs a
    cached token OR a password. The CC token short-circuits the password read.
    """
    meta = cred.get_account_metadata(idx)
    if meta is None or not meta.username:
        return None
    label = meta.label or meta.username
    if meta.game == "ttr":
        acct = cred.get_account(idx)
        launchable = bool(acct and acct.password)
    else:  # cc
        # getattr (not meta.launcher_token) so a partial CredentialsManager-like
        # double without the field still works; the real model always has it.
        if getattr(meta, "launcher_token", ""):
            launchable = True
        else:
            acct = cred.get_account(idx)
            launchable = bool(acct and acct.password)
    return (meta.game, label, launchable)


def build_recent_menu_model(ordered_ids, account_for, is_running,
                            keyring_available, account_count, limit=4) -> RecentMenuModel:
    """Build the recent-launch menu model.

    - ``ordered_ids``: account IDs, most-recent-first (from RecentLaunchesStore).
    - ``account_for(aid)``: ``(game, display_label, launchable) | None``.
    - ``is_running(game, aid)``: True if a launcher for the account is running.
    - ``keyring_available`` / ``account_count``: drive the status precedence.

    Returns a ``RecentMenuModel``. If keyring is unavailable AND accounts exist, it
    short-circuits to ``keyring_locked`` with no per-account resolution (avoids a
    lock-timeout storm). Otherwise it walks the ids, skipping deleted/running/
    unlaunchable, stops at ``limit`` survivors, and reports ``ok`` (or ``empty``).
    """
    if not keyring_available and account_count > 0:
        return RecentMenuModel((), False, "keyring_locked")
    items = []
    for aid in ordered_ids:
        if len(items) >= limit:
            break
        view = account_for(aid)
        if view is None:
            continue
        game, display_label, launchable = view
        if is_running(game, aid):
            continue
        if not launchable:
            continue
        items.append(MenuItem(aid, game, display_label))
    if not items:
        return RecentMenuModel((), False, "empty")
    mixed = {"ttr", "cc"} <= {it.game for it in items}
    return RecentMenuModel(tuple(items), mixed, "ok")
