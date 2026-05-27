"""Unified held-key registry used by the InputService to track keys the
user is currently holding, tagged by dispatch kind.

Replaces three previous disjoint sets in InputService (keys_held,
modifiers_held, action_held). A single container with a HoldKind
discriminator eliminates the bug class of forgetting to drain one bucket
on focus loss or shutdown.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
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


class HeldKeyRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, HeldKey] = {}

    def acquire(self, key: str, kind: HoldKind, pressed_at: float) -> bool:
        if key in self._entries:
            return False
        self._entries[key] = HeldKey(key=key, kind=kind, pressed_at=pressed_at)
        return True

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
