"""Unit tests for GameRegistry singleton and PID classification."""

import sys
from unittest.mock import patch

import pytest
from utils.game_registry import GameRegistry, _KNOWN_X11_CLASSES

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


@pytest.mark.skipif(sys.platform == "win32", reason="X11 fallback is Linux-only")
class TestX11ClassFallback:
    """Flatpak sandbox cannot read /proc/<host_pid>/exe; get_game_for_window
    must still classify the window via its X11 WM_CLASS."""

    def test_known_classes_table_covers_both_games(self):
        # Sanity check: the canonical class strings are the ones the games set.
        assert _KNOWN_X11_CLASSES.get("toontown rewritten") == "ttr"
        assert _KNOWN_X11_CLASSES.get("corporate clash") == "cc"

    def test_falls_back_to_x11_class_when_pid_unresolvable(self):
        reg = GameRegistry.instance()
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=None), \
             patch.object(GameRegistry, "_tag_from_x11_class", return_value="ttr") as m:
            assert reg.get_game_for_window("0x1234") == "ttr"
            m.assert_called_once_with("0x1234")

    def test_falls_back_to_x11_class_when_proc_exe_missing(self):
        """The Flatpak case: XRes gives a host PID, but /proc/<pid>/exe is
        unreadable from inside the sandbox, so _tag_from_process_name returns
        None. We must still classify via WM_CLASS, not give up."""
        reg = GameRegistry.instance()
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=PID_A), \
             patch.object(GameRegistry, "_tag_from_process_name", return_value=None), \
             patch.object(GameRegistry, "_tag_from_x11_class", return_value="cc") as m:
            # PID_A is not registered so get_game(PID_A) returns None too.
            assert reg.get_game_for_window("0xabcd") == "cc"
            m.assert_called_once_with("0xabcd")

    def test_proc_name_wins_over_x11_class_when_available(self):
        """X11 fallback only runs when /proc lookup fails — don't trample a
        successful process-name match."""
        reg = GameRegistry.instance()
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=PID_A), \
             patch.object(GameRegistry, "_tag_from_process_name", return_value="ttr"), \
             patch.object(GameRegistry, "_tag_from_x11_class") as m:
            assert reg.get_game_for_window("0xabcd") == "ttr"
            m.assert_not_called()

    def test_registered_pid_wins_over_x11_class(self):
        """An explicitly registered PID (launched by us) should still beat
        any fallback path."""
        reg = GameRegistry.instance()
        reg.register(PID_A, "ttr")
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=PID_A), \
             patch.object(GameRegistry, "_tag_from_process_name") as proc_m, \
             patch.object(GameRegistry, "_tag_from_x11_class") as x11_m:
            assert reg.get_game_for_window("0xabcd") == "ttr"
            proc_m.assert_not_called()
            x11_m.assert_not_called()

    def test_unknown_class_returns_none(self):
        reg = GameRegistry.instance()
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=None), \
             patch.object(GameRegistry, "_tag_from_x11_class", return_value=None):
            assert reg.get_game_for_window("0x1234") is None
