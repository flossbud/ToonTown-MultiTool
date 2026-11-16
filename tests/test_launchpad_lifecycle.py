"""Launchpad window lifecycle: the handoff's table and DESIGN.md's rules,
table-driven. Each case is a list of (event, args, expected commands)."""
import pytest

from utils.widgets.launchpad.lifecycle import (
    ACCOUNT, ACCOUNTS, HIDDEN, KEYSETS, LAUNCHER, MINIMIZED, SETTINGS, VISIBLE,
    Command, WindowLifecycle,
)

SHOW_LAUNCHER = [Command("show", LAUNCHER)]
HIDE = [Command("hide")]
MIN = [Command("minimize")]
QUIT = [Command("quit")]

CASES = {
    # Handoff table, row 1: app starts, no game windows.
    "starts shown on the launcher": [
        ("started", (), SHOW_LAUNCHER),
    ],
    # Row 2: launches pending, the window stays up.
    "stays up while launches are pending": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_pending", ("b",), []),
        ("windows", (1,), []),
    ],
    # Row 3: hides when the LAST pending launch lands, not the first.
    "hides on the last landing, not the first": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_pending", ("b",), []),
        ("launch_pending", ("c",), []),
        ("windows", (1,), []),
        ("launch_landed", ("a",), []),
        ("windows", (2,), []),
        ("launch_landed", ("b",), []),
        ("windows", (3,), []),
        ("launch_landed", ("c",), HIDE),
    ],
    "a launch added mid-batch keeps it open": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_pending", ("b",), []),
        ("launch_landed", ("a",), []),
        ("launch_pending", ("c",), []),
        ("launch_landed", ("b",), []),
        ("launch_landed", ("c",), HIDE),
    ],
    "the setting off keeps the window up": [
        ("setting_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_landed", ("a",), []),
    ],
    "the setting can be turned back on": [
        ("setting_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("setting_changed", (True,), []),
        ("launch_pending", ("a",), []),
        ("launch_landed", ("a",), HIDE),
    ],
    "a failure in the batch keeps the window up": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_pending", ("b",), []),
        ("launch_failed", ("a",), []),
        ("launch_landed", ("b",), []),
    ],
    "a batch that only failed keeps the window up": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_failed", ("a",), []),
    ],
    "the next batch starts clean after a failure": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_failed", ("a",), []),
        ("launch_pending", ("b",), []),
        ("launch_landed", ("b",), HIDE),
    ],
    "unknown launches are ignored": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_landed", ("x",), []),
        ("launch_failed", ("x",), []),
    ],
    "a landing while hidden does nothing": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_landed", ("a",), HIDE),
        ("windows", (1,), []),
        ("launch_pending", ("b",), []),      # from the strip's compact launcher
        ("launch_landed", ("b",), []),
        ("windows", (2,), []),
    ],
    # Row 4: home block or tray asks for something.
    "the home block opens settings": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_landed", ("a",), HIDE),
        ("windows", (1,), []),
        ("requested", (SETTINGS,), [Command("show", SETTINGS)]),
    ],
    "the tray opens an account": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("close_requested", (), HIDE),
        ("requested", (ACCOUNT, "acct-1"), [Command("show", ACCOUNT, "acct-1")]),
    ],
    "an account with no id falls back to Accounts": [
        ("started", (), SHOW_LAUNCHER),
        ("requested", (ACCOUNT,), [Command("show", ACCOUNTS)]),
    ],
    "an unknown target falls back to the launcher": [
        ("started", (), SHOW_LAUNCHER),
        ("requested", ("nonsense",), SHOW_LAUNCHER),
    ],
    "a request while visible still opens the sheet": [
        ("started", (), SHOW_LAUNCHER),
        ("requested", (KEYSETS,), [Command("show", KEYSETS)]),
    ],
    "closing after a request hides it again": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (2,), []),
        ("close_requested", (), HIDE),
        ("requested", (SETTINGS,), [Command("show", SETTINGS)]),
        ("close_requested", (), HIDE),
    ],
    # Row 5: last game window closes.
    "shown again on the launcher when the last game window closes": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_pending", ("b",), []),
        ("windows", (2,), []),
        ("launch_landed", ("a",), []),
        ("launch_landed", ("b",), HIDE),
        ("windows", (1,), []),
        ("windows", (0,), SHOW_LAUNCHER),
    ],
    "a visible window is not pulled back to the launcher": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("requested", (SETTINGS,), [Command("show", SETTINGS)]),
        ("windows", (0,), []),
    ],
    # Close rules.
    "closing with game windows hides": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (3,), []),
        ("close_requested", (), HIDE),
        ("close_requested", (), []),           # already hidden
    ],
    "closing with no game windows quits": [
        ("started", (), SHOW_LAUNCHER),
        ("close_requested", (), QUIT),
    ],
    "closing with launches pending hides instead of quitting": [
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("close_requested", (), HIDE),
        ("launch_landed", ("a",), []),         # already hidden
        ("windows", (1,), []),
    ],
    "closing after the last window closed quits": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("windows", (0,), []),
        ("close_requested", (), QUIT),
    ],
    # No tray: minimize instead of hide, everywhere.
    "no tray: the last landing minimizes": [
        ("tray_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("launch_pending", ("a",), []),
        ("launch_landed", ("a",), MIN),
    ],
    "no tray: closing with game windows minimizes": [
        ("tray_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("close_requested", (), MIN),
        ("close_requested", (), []),
    ],
    "no tray: closing with no game windows still quits": [
        ("tray_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("close_requested", (), QUIT),
    ],
    "no tray: a minimized window comes back on request": [
        ("tray_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("close_requested", (), MIN),
        ("requested", (SETTINGS,), [Command("show", SETTINGS)]),
    ],
    "no tray: a minimized window is restored when the last game closes": [
        ("tray_changed", (False,), []),
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("close_requested", (), MIN),
        ("windows", (0,), SHOW_LAUNCHER),
    ],
    "losing the tray while hidden minimizes": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("close_requested", (), HIDE),
        ("tray_changed", (False,), MIN),
    ],
    "losing the tray while visible changes nothing": [
        ("started", (), SHOW_LAUNCHER),
        ("windows", (1,), []),
        ("tray_changed", (False,), []),
    ],
}


@pytest.mark.parametrize("name", list(CASES))
def test_lifecycle(name):
    lc = WindowLifecycle()
    for step, (event, args, expected) in enumerate(CASES[name]):
        got = getattr(lc, event)(*args)
        assert got == expected, f"step {step}: {event}{args} -> {got}, want {expected}"


def test_state_after_a_full_session():
    lc = WindowLifecycle()
    lc.started()
    assert lc.window == VISIBLE
    lc.launch_pending("a")
    assert lc.pending == {"a"}
    lc.windows(1)
    lc.launch_landed("a")
    assert lc.window == HIDDEN and lc.pending == set()
    lc.windows(0)
    assert lc.window == VISIBLE


def test_started_with_game_windows_already_up():
    """A restart while games run: shown on the launcher, and closing it
    hides (the games are still there) instead of quitting."""
    lc = WindowLifecycle()
    assert lc.started(live_windows=2) == SHOW_LAUNCHER
    assert lc.close_requested() == HIDE


def test_constructor_carries_the_inputs():
    lc = WindowLifecycle(hide_when_toons_up=False, tray_available=False)
    lc.started()
    lc.launch_pending("a")
    assert lc.launch_landed("a") == []
    lc.windows(1)
    assert lc.close_requested() == MIN
    assert lc.window == MINIMIZED
