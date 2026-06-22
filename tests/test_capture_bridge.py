import os
import pytest
from utils.game_registry import GameRegistry


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display")
def test_pid_for_window_returns_none_for_garbage_window():
    # A non-existent window id resolves to None, never raises.
    # Note: "0" is the X11 root window and does have a PID; use a high XID
    # value that no server will ever allocate (above practical XID ceiling).
    assert GameRegistry.pid_for_window("4294967295") is None


class _FakeSettings:
    def __init__(self): self.d = {}
    def get(self, k, default=None): return self.d.get(k, default)
    def set(self, k, v): self.d[k] = v


class _LaunchTabBridge:
    """Minimal stand-in exercising the exact bridge logic added to LaunchTab."""
    def __init__(self, sm):
        from utils.recent_toons import RecentToonsStore
        self._pid_to_account = {}
        self._recent_toons = RecentToonsStore(sm)

    def on_game_launched(self, game, account_id, pid):
        self._pid_to_account[pid] = (game, account_id)

    def on_game_exited(self, pid):
        self._pid_to_account.pop(pid, None)

    def capture_toon(self, pid, toon_name, dna):
        ga = self._pid_to_account.get(pid)
        if not ga:
            return
        game, account_id = ga
        self._recent_toons.record(account_id, toon_name, game, dna)


def test_bridge_records_toon_for_launched_account():
    from utils.recent_toons import ToonRecord
    sm = _FakeSettings(); lt = _LaunchTabBridge(sm)
    lt.on_game_launched("ttr", "acct-1", pid=4242)
    lt.capture_toon(4242, "Sir Hopper", "dna-xyz")
    assert lt._recent_toons.get("acct-1") == ToonRecord("Sir Hopper", "ttr", "dna-xyz")


def test_bridge_ignores_toon_for_unknown_pid():
    sm = _FakeSettings(); lt = _LaunchTabBridge(sm)
    lt.capture_toon(9999, "Ghost", "d")
    assert sm.d.get("recent_toons", {}) == {}


def test_exit_clears_pid_mapping():
    sm = _FakeSettings(); lt = _LaunchTabBridge(sm)
    lt.on_game_launched("cc", "acct-2", pid=7)
    lt.on_game_exited(7)
    lt.capture_toon(7, "Too Late", "d")
    assert sm.d.get("recent_toons", {}) == {}
