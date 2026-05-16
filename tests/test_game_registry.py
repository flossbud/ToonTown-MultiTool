"""Unit tests for GameRegistry singleton and PID classification."""

import sys
from unittest.mock import mock_open, patch

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


@pytest.mark.skipif(sys.platform == "win32", reason="Wine helper path is Linux-only")
class TestWineHelperCmdline:
    """Wine/Proton hosts every Windows .exe under wine64-preloader, so
    /proc/<pid>/exe is the same string for every Wine app. The real game
    identity lives in argv[0], the Windows-style path Wine was asked to
    launch. Without this fallback, Proton-launched Corporate Clash
    (and any future Wine-only game) cannot be identified, and the
    multitool's trust filter rejects every Toon window as 'confirmed not
    a game'."""

    def test_tag_from_wine_cmdline_resolves_cc_under_wine64_preloader(self):
        cc_argv0 = (
            b"C:\\users\\steamuser\\AppData\\Local\\Corporate Clash\\"
            b"CorporateClash.exe\x00--some-flag\x00"
        )
        with patch.object(
            GameRegistry, "_get_process_name", return_value="wine64-preloader"
        ), patch("builtins.open", mock_open(read_data=cc_argv0)):
            assert GameRegistry._tag_from_wine_cmdline(PID_A) == "cc"

    def test_tag_from_wine_cmdline_resolves_ttr_under_wine_preloader(self):
        # If someone ever runs TTR through Wine (Steam Deck, etc), the same
        # path should work.
        ttr_argv0 = b"C:\\Program Files\\Toontown Rewritten\\TTREngine64.exe\x00"
        with patch.object(
            GameRegistry, "_get_process_name", return_value="wine-preloader"
        ), patch("builtins.open", mock_open(read_data=ttr_argv0)):
            assert GameRegistry._tag_from_wine_cmdline(PID_A) == "ttr"

    def test_tag_from_wine_cmdline_returns_none_for_non_wine_process(self):
        # Bare /proc/<pid>/exe of a normal Linux process: not a wine helper,
        # don't even bother reading cmdline.
        with patch.object(
            GameRegistry, "_get_process_name", return_value="firefox"
        ):
            assert GameRegistry._tag_from_wine_cmdline(PID_A) is None

    def test_tag_from_wine_cmdline_returns_none_for_unknown_wine_app(self):
        # Wine launching something we don't recognise: don't classify it.
        other_argv0 = b"C:\\Program Files\\Notepad\\notepad.exe\x00"
        with patch.object(
            GameRegistry, "_get_process_name", return_value="wine64-preloader"
        ), patch("builtins.open", mock_open(read_data=other_argv0)):
            assert GameRegistry._tag_from_wine_cmdline(PID_A) is None

    def test_tag_from_wine_cmdline_handles_oserror(self):
        # Race: process exited between exe-read and cmdline-read.
        with patch.object(
            GameRegistry, "_get_process_name", return_value="wine64-preloader"
        ), patch("builtins.open", side_effect=OSError("gone")):
            assert GameRegistry._tag_from_wine_cmdline(PID_A) is None

    def test_get_game_for_window_uses_wine_cmdline_when_proc_name_unknown(self):
        """End-to-end: PID resolves to a wine preloader, _tag_from_process_name
        returns None (wine-preloader is not in _KNOWN_PROCESSES), but
        _tag_from_wine_cmdline finds CC in argv[0]. The multitoon API router
        gets 'cc' instead of falling all the way through to None."""
        reg = GameRegistry.instance()
        with patch.object(GameRegistry, "_get_pid_for_window", return_value=PID_A), \
             patch.object(GameRegistry, "_tag_from_process_name", return_value=None), \
             patch.object(GameRegistry, "_tag_from_wine_cmdline", return_value="cc"), \
             patch.object(GameRegistry, "_tag_from_x11_class") as x11_m:
            assert reg.get_game_for_window("0x6e00001") == "cc"
            x11_m.assert_not_called()

    def test_classify_window_for_filtering_accepts_cc_under_wine(self):
        """The trust filter previously returned (None, True) for every wine
        window (preloader exe not in _KNOWN_PROCESSES), which made
        window_manager._accept_candidate_window reject the real game window.
        With the wine-cmdline branch it now returns ('cc', True) and the
        window is kept."""
        reg = GameRegistry.instance()
        with patch.object(
            GameRegistry,
            "_get_host_pid_for_window_xres",
            return_value=PID_A,
        ), patch.object(
            GameRegistry, "_get_process_name", return_value="wine64-preloader"
        ), patch.object(
            GameRegistry, "_tag_from_wine_cmdline", return_value="cc"
        ):
            game, confirmed = reg.classify_window_for_filtering("0x6e00001")
            assert (game, confirmed) == ("cc", True)

    def test_classify_window_for_filtering_rejects_non_game_wine_helper(self):
        """A wine helper hosting something unrelated (e.g. conhost.exe console
        sibling) must still be confirmed-not-a-game so window_manager
        rejects it."""
        reg = GameRegistry.instance()
        with patch.object(
            GameRegistry,
            "_get_host_pid_for_window_xres",
            return_value=PID_A,
        ), patch.object(
            GameRegistry, "_get_process_name", return_value="wine64-preloader"
        ), patch.object(
            GameRegistry, "_tag_from_wine_cmdline", return_value=None
        ):
            assert reg.classify_window_for_filtering("0x6a00001") == (None, True)
