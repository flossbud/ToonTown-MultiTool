"""Repro for v2.1.3 issue 5: launch tab button reverts to "Launch" while
status dot stays green after a card rebuild (_build_ui).

Root cause: _build_ui resets self._cards = {"ttr": [], "cc": []} and
rebuilds via _make_row, which initializes the launch button text to
"Launch". But self._launchers — the truth source consulted by
update_dot_state to keep the dot in sync — is NOT reset. So the button
desynced from the running launcher.

Fix: after _build_ui repopulates self._cards, walk self._launchers and
re-apply LoginState.RUNNING for any slot whose launcher is still alive.

This test exercises the new helper _restore_running_state_from_launchers
in isolation, using LaunchTab.__new__ to skip the heavy __init__ that
spins up a keyring probe thread.
"""
from unittest.mock import MagicMock

import pytest

from tabs.launch_tab import LaunchTab, LoginState


class _FakeLauncher:
    def __init__(self, running: bool):
        self._running = running

    def is_running(self) -> bool:
        return self._running


def _bare_launch_tab():
    """Create a LaunchTab without invoking __init__ — we only want to
    exercise the _restore_running_state_from_launchers method, which
    only consults self._launchers, self._cards, and self._update_status."""
    tab = LaunchTab.__new__(LaunchTab)
    tab._launchers = {"ttr": [None] * 4, "cc": [None] * 4}
    tab._cards = {
        "ttr": [{"launch_btn": MagicMock(text=lambda: "Launch")} for _ in range(4)],
        "cc":  [{"launch_btn": MagicMock(text=lambda: "Launch")} for _ in range(4)],
    }
    tab._update_status = MagicMock()
    return tab


def test_restore_running_state_calls_update_status_for_running_slots():
    tab = _bare_launch_tab()
    tab._launchers["ttr"][0] = _FakeLauncher(running=True)
    tab._launchers["ttr"][2] = _FakeLauncher(running=True)

    tab._restore_running_state_from_launchers()

    calls = tab._update_status.call_args_list
    args = sorted((c.args[0], c.args[1]) for c in calls)
    assert args == [("ttr", 0), ("ttr", 2)], (
        f"Expected _update_status calls for (ttr, 0) and (ttr, 2), got {args}"
    )
    for c in calls:
        assert c.args[2] == LoginState.RUNNING


def test_restore_running_state_skips_dead_launchers():
    """A launcher reference that exists but reports is_running()=False
    must not trigger a status update — the game is no longer alive."""
    tab = _bare_launch_tab()
    tab._launchers["ttr"][1] = _FakeLauncher(running=False)

    tab._restore_running_state_from_launchers()

    tab._update_status.assert_not_called()


def test_restore_running_state_skips_none_slots():
    """Slots with no launcher (the common case for unused account rows)
    must be skipped entirely."""
    tab = _bare_launch_tab()
    # All slots remain None.
    tab._restore_running_state_from_launchers()
    tab._update_status.assert_not_called()


def test_restore_running_state_handles_card_count_below_launcher_count():
    """If _cards has fewer entries than _launchers (e.g. the user lowered
    max_accounts_per_game and a former-active slot index is now beyond the
    visible cards), the helper must not raise IndexError — it should skip
    those slots."""
    tab = _bare_launch_tab()
    tab._cards["ttr"] = tab._cards["ttr"][:2]  # only 2 cards remain
    tab._launchers["ttr"][3] = _FakeLauncher(running=True)  # but slot 3 has a launcher

    # Should not raise.
    tab._restore_running_state_from_launchers()
    tab._update_status.assert_not_called()


def test_restore_running_state_handles_both_games():
    """TTR and CC launchers are tracked separately; both must be honored."""
    tab = _bare_launch_tab()
    tab._launchers["ttr"][0] = _FakeLauncher(running=True)
    tab._launchers["cc"][1] = _FakeLauncher(running=True)

    tab._restore_running_state_from_launchers()

    args = sorted((c.args[0], c.args[1]) for c in tab._update_status.call_args_list)
    assert args == [("cc", 1), ("ttr", 0)]
