"""macOS Click Sync mouse delivery engine (private SkyLight per-window path).

Pure record/field builders (this section) + the native delivery engine (Task 2).
Mechanism + record bytes proven in scripts/macos_click_delivery_spike.py and
docs/superpowers/specs/2026-06-13-macos-click-sync-port-design.md Section 2. The
pure helpers below carry NO PyObjC import so they unit-test on any host.
"""
from __future__ import annotations

import time

# kCGEventSourceUserData marker stamped on every posted event (echo filter).
# Same value as utils.macos_backend.SPIKE_EVENT_TAG so capture filters both paths.
SPIKE_EVENT_TAG = 0x7474_6D74  # "ttmt"

LEDGER_TTL = 0.25  # seconds a posted-event signature stays "ours" for echo matching

FOCUS_RECORD_SIZE = 0xF8  # 248-byte SkyLight event record


def build_activate_record(window_id: int) -> bytes:
    """The 0x0d "focused app for input routing" record (cua/yabai), posted to the
    TARGET PSN. Bytes: [0x04]=0xF8, [0x08]=0x0D, [0x3C:0x40]=wid (LE u32), [0x8A]=0x01."""
    rec = bytearray(FOCUS_RECORD_SIZE)
    rec[0x04] = 0xF8
    rec[0x08] = 0x0D
    rec[0x3C:0x40] = int(window_id).to_bytes(4, "little")
    rec[0x8A] = 0x01
    return bytes(rec)


def make_key_record(window_id: int, mode: int) -> bytes:
    """yabai make_key_window record, posted TWICE to the TARGET PSN (mode 0x01 then
    0x02). Bytes: [0x04]=0xF8, [0x08]=mode, [0x3A]=0x10, [0x3C:0x40]=wid (LE u32),
    [0x20:0x30]=0xff."""
    rec = bytearray(FOCUS_RECORD_SIZE)
    rec[0x04] = 0xF8
    rec[0x08] = int(mode) & 0xFF
    rec[0x3A] = 0x10
    rec[0x3C:0x40] = int(window_id).to_bytes(4, "little")
    for i in range(0x20, 0x30):
        rec[i] = 0xFF
    return bytes(rec)


def mouse_event_fields(pid: int, window_id: int) -> list[tuple[int, int, bool]]:
    """(field_id, value, via_private) stamped on every mouse CGEvent. Proven values
    from the spike's positive control. Private fields use SLEventSetIntegerValueField."""
    return [
        (1, 1, False),         # kCGMouseEventClickState
        (3, 0, False),         # kCGMouseEventButtonNumber (left = 0)
        (7, 3, False),         # kCGMouseEventSubtype
        (40, int(pid), True),  # kCGEventTargetUnixProcessID (private setter)
        (91, int(window_id), True),
        (92, int(window_id), True),
    ]


# kind -> (NSEventType int, Quartz CGEventType attribute name). The native layer
# resolves the attribute name against the Quartz module at post time.
EVENT_KINDS = {
    "move":    (5, "kCGEventMouseMoved"),
    "down":    (1, "kCGEventLeftMouseDown"),
    "up":      (2, "kCGEventLeftMouseUp"),
    "dragged": (6, "kCGEventLeftMouseDragged"),
}


def click_count_for(kind: str) -> int:
    """NSEvent clickCount: 0 for a bare move, 1 for button-bearing events."""
    return 0 if kind == "move" else 1


class EchoLedger:
    """Shared record of recently POSTED event signatures. The SAME instance is wired
    into the delivery engine (which `record`s every posted event) and the capture
    EchoGuard (which `matches` to recognize an injected event that re-entered the tap
    WITHOUT our marker - a marker-stripping OS revision). Signature buckets the screen
    point so float jitter still matches. Event-type ints are the mouse CGEventType
    values, which equal the NSEventType values for these kinds (down=1, up=2, moved=5,
    dragged=6), so the delivery side (NSEventType) and the capture side (CGEventType)
    agree on the key. Single-threaded use (the dispatcher thread) - no lock needed."""

    def __init__(self, ttl: float = LEDGER_TTL):
        self._ttl = float(ttl)
        self._sigs: dict[tuple[int, int, int], float] = {}   # signature -> expiry (monotonic)

    @staticmethod
    def _sig(event_type: int, root_x: float, root_y: float) -> tuple[int, int, int]:
        return (int(event_type), round(float(root_x) / 2), round(float(root_y) / 2))

    def _evict(self, t: float) -> None:
        """Drop expired signatures. Called from BOTH record() and matches() so the
        dict stays bounded even when one side is idle (e.g. the delivery engine posts
        while capture is stopped, so matches() is never called)."""
        for k in [k for k, exp in self._sigs.items() if exp < t]:
            self._sigs.pop(k, None)

    def record(self, event_type: int, root_x: float, root_y: float, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        self._evict(t)
        self._sigs[self._sig(event_type, root_x, root_y)] = t + self._ttl

    def matches(self, event_type: int, root_x: float, root_y: float, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        self._evict(t)
        exp = self._sigs.get(self._sig(event_type, root_x, root_y))
        return exp is not None and exp >= t
