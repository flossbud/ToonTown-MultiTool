"""Unit tests for the HeldKeyRegistry data structure.

Pure-Python data structure, no I/O, no threading. Locks in the
acquire / release / drain / contains / keys_by_kind contract used by
InputService to track held keys across three dispatch kinds.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

from utils.held_key_registry import HoldKind, HeldKey, HeldKeyRegistry


def test_acquire_returns_true_first_time():
    reg = HeldKeyRegistry()
    assert reg.acquire("space", HoldKind.MOVEMENT, 1.0) is True


def test_acquire_returns_false_on_repeat():
    reg = HeldKeyRegistry()
    reg.acquire("space", HoldKind.MOVEMENT, 1.0)
    assert reg.acquire("space", HoldKind.MOVEMENT, 2.0) is False


def test_release_returns_entry_first_time():
    reg = HeldKeyRegistry()
    reg.acquire("Delete", HoldKind.MOVEMENT, 5.0)
    entry = reg.release("Delete")
    assert entry is not None
    assert entry.key == "Delete"
    assert entry.kind == HoldKind.MOVEMENT
    assert entry.pressed_at == 5.0


def test_release_returns_none_after_first_release():
    reg = HeldKeyRegistry()
    reg.acquire("Delete", HoldKind.MOVEMENT, 5.0)
    reg.release("Delete")
    assert reg.release("Delete") is None


def test_release_of_unknown_key_returns_none():
    reg = HeldKeyRegistry()
    assert reg.release("never_held") is None


def test_contains_reflects_acquire_and_release():
    reg = HeldKeyRegistry()
    assert reg.contains("Shift_L") is False
    reg.acquire("Shift_L", HoldKind.MODIFIER, 0.0)
    assert reg.contains("Shift_L") is True
    reg.release("Shift_L")
    assert reg.contains("Shift_L") is False


def test_keys_by_kind_filters_correctly():
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 0.0)
    reg.acquire("Shift_L", HoldKind.MODIFIER, 0.0)
    reg.acquire("F5", HoldKind.ACTION, 0.0)
    reg.acquire("space", HoldKind.MOVEMENT, 0.0)
    movement = set(reg.keys_by_kind(HoldKind.MOVEMENT))
    modifier = set(reg.keys_by_kind(HoldKind.MODIFIER))
    action = set(reg.keys_by_kind(HoldKind.ACTION))
    assert movement == {"w", "space"}
    assert modifier == {"Shift_L"}
    assert action == {"F5"}


def test_drain_returns_all_entries_and_clears():
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    reg.acquire("Shift_L", HoldKind.MODIFIER, 2.0)
    reg.acquire("F5", HoldKind.ACTION, 3.0)
    drained = reg.drain()
    keys = {e.key for e in drained}
    assert keys == {"w", "Shift_L", "F5"}
    assert len(reg) == 0
    assert reg.contains("w") is False


def test_drain_on_empty_returns_empty_list():
    reg = HeldKeyRegistry()
    assert reg.drain() == []


def test_pressed_at_is_captured_per_entry():
    reg = HeldKeyRegistry()
    reg.acquire("a", HoldKind.MOVEMENT, 10.5)
    reg.acquire("b", HoldKind.MOVEMENT, 20.25)
    by_key = {e.key: e.pressed_at for e in reg.drain()}
    assert by_key == {"a": 10.5, "b": 20.25}


def test_len_reflects_size():
    reg = HeldKeyRegistry()
    assert len(reg) == 0
    reg.acquire("w", HoldKind.MOVEMENT, 0.0)
    assert len(reg) == 1
    reg.acquire("Shift_L", HoldKind.MODIFIER, 0.0)
    assert len(reg) == 2
    reg.release("w")
    assert len(reg) == 1


def test_mixed_kinds_coexist_independently():
    """Three kinds tracked simultaneously; release of one does not affect
    the others; drain returns all three exactly once."""
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    reg.acquire("Shift_L", HoldKind.MODIFIER, 2.0)
    reg.acquire("F5", HoldKind.ACTION, 3.0)
    assert reg.release("Shift_L").kind == HoldKind.MODIFIER
    assert reg.contains("w") is True
    assert reg.contains("F5") is True
    remaining = reg.drain()
    assert {e.key for e in remaining} == {"w", "F5"}


def test_record_sends_attaches_delivered_pairs_to_entry():
    """The keydown dispatcher records the (window, keysym) pairs it actually
    delivered; the release entry carries them so the keyup can replay exactly
    what the keydown pressed instead of re-translating the physical key."""
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    reg.record_sends("w", [("w1", "Up"), ("w2", "w")])
    entry = reg.release("w")
    assert entry.sends == (("w1", "Up"), ("w2", "w"))


def test_sends_defaults_to_none_when_never_recorded():
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    assert reg.release("w").sends is None


def test_record_sends_on_unheld_key_is_noop():
    """A dispatch racing a drain: the drain already released everything the
    keydown sent, so a late record must not resurrect an entry."""
    reg = HeldKeyRegistry()
    reg.record_sends("w", [("w1", "Up")])
    assert len(reg) == 0
    assert reg.contains("w") is False


def test_drain_preserves_recorded_sends():
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    reg.record_sends("w", [("w1", "Up")])
    reg.acquire("d", HoldKind.MOVEMENT, 2.0)
    by_key = {e.key: e.sends for e in reg.drain()}
    assert by_key == {"w": (("w1", "Up"),), "d": None}


def test_record_sends_empty_is_recorded_not_none():
    """An empty record means 'the keydown delivered nothing' (e.g. chat was
    active) and must replay nothing - distinct from None (never recorded),
    which falls back to legacy re-translation."""
    reg = HeldKeyRegistry()
    reg.acquire("w", HoldKind.MOVEMENT, 1.0)
    reg.record_sends("w", [])
    assert reg.release("w").sends == ()
