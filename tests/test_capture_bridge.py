import os
import pytest
from utils.game_registry import GameRegistry


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display")
def test_pid_for_window_returns_none_for_garbage_window():
    # A non-existent window id resolves to None, never raises.
    # Note: "0" is the X11 root window and does have a PID; use a high XID
    # value that no server will ever allocate (above practical XID ceiling).
    assert GameRegistry.pid_for_window("4294967295") is None


class _FakeStore:
    def __init__(self): self.calls = []
    def record(self, account_id, toon_name, game, dna=""):
        self.calls.append((account_id, toon_name, game, dna))


def test_bridge_records_toon_for_launched_account():
    from utils.toon_capture_bridge import ToonCaptureBridge
    s = _FakeStore(); b = ToonCaptureBridge(s)
    b.record_launch(4242, "ttr", "acct-1")
    b.capture(4242, "Sir Hopper", "dna-xyz")
    assert s.calls == [("acct-1", "Sir Hopper", "ttr", "dna-xyz")]


def test_bridge_ignores_unknown_pid():
    from utils.toon_capture_bridge import ToonCaptureBridge
    s = _FakeStore(); b = ToonCaptureBridge(s)
    b.capture(9999, "Ghost", "d")
    assert s.calls == []


def test_clear_account_drops_mapping_by_value():
    from utils.toon_capture_bridge import ToonCaptureBridge
    s = _FakeStore(); b = ToonCaptureBridge(s)
    b.record_launch(100, "ttr", "acct-1")
    b.clear_account("ttr", "acct-1")
    b.capture(100, "Too Late", "d")
    assert s.calls == []


def test_clear_account_leaves_other_accounts():
    from utils.toon_capture_bridge import ToonCaptureBridge
    s = _FakeStore(); b = ToonCaptureBridge(s)
    b.record_launch(100, "ttr", "acct-1")
    b.record_launch(200, "cc", "acct-2")
    b.clear_account("ttr", "acct-1")
    b.capture(200, "Alive", "")
    assert s.calls == [("acct-2", "Alive", "cc", "")]


def test_toon_changed_dedup():
    from utils.toon_capture_bridge import toon_changed
    seen = {}
    assert toon_changed(seen, "w1", "Toon", "d") is True
    seen["w1"] = ("Toon", "d")
    assert toon_changed(seen, "w1", "Toon", "d") is False
    assert toon_changed(seen, "w1", "Toon", "d2") is True
