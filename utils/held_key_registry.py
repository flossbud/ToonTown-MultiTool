"""Unified held-key registry used by the InputService to track keys the
user is currently holding, tagged by dispatch kind.

Replaces three previous disjoint sets in InputService (keys_held,
modifiers_held, action_held). A single container with a HoldKind
discriminator eliminates the bug class of forgetting to drain one bucket
on focus loss or shutdown.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Optional


class HoldKind(Enum):
    MOVEMENT = auto()
    MODIFIER = auto()
    ACTION = auto()


@dataclass(frozen=True)
class HeldKey:
    key: str
    kind: HoldKind
    pressed_at: float
    # The (window_id, keysym) pairs the keydown ACTUALLY delivered, recorded
    # at dispatch time. A keyup/drain that finds a non-None value replays
    # keyups to exactly these targets instead of re-translating the physical
    # key through the CURRENT keymap assignments — re-translation is what
    # stranded a synthesized key when the toon's keyset was switched mid-hold
    # (the new set no longer binds the physical key, so the keyup resolved to
    # nothing). None means "not recorded" (paths that never dispatch through
    # the movement router) and keeps the legacy re-translate dispatch.
    sends: Optional[tuple[tuple[str, str], ...]] = None


class HeldKeyRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, HeldKey] = {}

    def acquire(self, key: str, kind: HoldKind, pressed_at: float) -> bool:
        if key in self._entries:
            return False
        self._entries[key] = HeldKey(key=key, kind=kind, pressed_at=pressed_at)
        return True

    def record_sends(self, key: str, sends) -> None:
        """Attach the delivered (window_id, keysym) pairs to an existing
        entry. No-op when the key is not held (a dispatch raced a drain) —
        the drain already released everything the keydown sent."""
        entry = self._entries.get(key)
        if entry is None:
            return
        self._entries[key] = replace(entry, sends=tuple(sends))

    def release(self, key: str) -> Optional[HeldKey]:
        return self._entries.pop(key, None)

    def contains(self, key: str) -> bool:
        return key in self._entries

    def keys_by_kind(self, kind: HoldKind) -> list[str]:
        return [k for k, e in self._entries.items() if e.kind == kind]

    def drain(self) -> list[HeldKey]:
        entries = list(self._entries.values())
        self._entries.clear()
        return entries

    def __len__(self) -> int:
        return len(self._entries)
