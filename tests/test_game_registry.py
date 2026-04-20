"""Unit tests for GameRegistry singleton and PID classification."""

import pytest
from utils.game_registry import GameRegistry

# Fake PIDs that won't collide with real processes.
PID_A = 99999
PID_B = 88888
PID_C = 77777


@pytest.fixture(autouse=True)
def _cleanup_registry():
    """Ensure fake PIDs are removed after every test."""
    yield
    reg = GameRegistry.instance()
    for pid in (PID_A, PID_B, PID_C):
        reg.unregister(pid)


class TestSingleton:
    def test_instance_returns_same_object(self):
        a = GameRegistry.instance()
        b = GameRegistry.instance()
        assert a is b


class TestRegisterAndClassify:
    def test_register_and_get_game(self):
        reg = GameRegistry.instance()
        reg.register(PID_A, "ttr")
        assert reg.get_game(PID_A) == "ttr"

    def test_classify_unknown_pid_returns_none(self):
        reg = GameRegistry.instance()
        assert reg.get_game(PID_A) is None

    def test_unregister_removes_classification(self):
        reg = GameRegistry.instance()
        reg.register(PID_A, "cc")
        reg.unregister(PID_A)
        assert reg.get_game(PID_A) is None

    def test_register_same_pid_overwrites_game_type(self):
        reg = GameRegistry.instance()
        reg.register(PID_A, "ttr")
        reg.register(PID_A, "cc")
        assert reg.get_game(PID_A) == "cc"

    def test_multiple_pids_independent(self):
        reg = GameRegistry.instance()
        reg.register(PID_A, "ttr")
        reg.register(PID_B, "cc")
        assert reg.get_game(PID_A) == "ttr"
        assert reg.get_game(PID_B) == "cc"

    def test_unregister_nonexistent_pid_is_noop(self):
        reg = GameRegistry.instance()
        # Should not raise.
        reg.unregister(PID_C)
