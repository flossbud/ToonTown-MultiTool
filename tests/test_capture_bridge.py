import os
import pytest
from utils.game_registry import GameRegistry


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display")
def test_pid_for_window_returns_none_for_garbage_window():
    # A non-existent window id resolves to None, never raises.
    # Note: "0" is the X11 root window and does have a PID; use a high XID
    # value that no server will ever allocate (above practical XID ceiling).
    assert GameRegistry.pid_for_window("4294967295") is None
