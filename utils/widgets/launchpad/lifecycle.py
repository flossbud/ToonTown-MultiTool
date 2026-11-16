"""When the launchpad window shows, hides, minimizes or quits.

A pure state machine (no Qt): the window feeds it events and carries out
the commands it returns. Rules, from the window handoff (section 1) and
DESIGN.md section 7:

| Moment                                   | Window                             |
| ---------------------------------------- | ---------------------------------- |
| App starts                               | Shown, on the launcher             |
| Launches pending                         | Stays up                           |
| Last pending launch lands                | Hides (if HIDE_WINDOW_WHEN_TOONS_UP)|
| Home block or tray asks for something    | Shown with the matching sheet      |
| Last game window closes                  | Shown again, on the launcher       |
| User closes the window                   | Hides while game windows exist,    |
|                                          | quits when none do                 |

Wherever the rules say hide and no system tray is available, the window
minimizes instead, so the app is never unreachable.

Choices the handoff leaves open (made here, conservatively):
- A batch of launches only hides the window if every launch in it landed.
  A failed one leaves the window up, because its card shows the failure
  (Fix login). The batch ends when the pending set empties.
- Closing the window while launches are still pending hides it rather than
  quitting, even with no game window up yet: quitting would abandon them.
- When the last game window closes and the window is already visible,
  nothing happens (it is not pulled back to the launcher).

The window maps its own signals to these events: launch_pending /
launch_landed / launch_failed from the launcher's launch paths, windows
from the WindowManager, requested from the home block and the tray,
close_requested from closeEvent, and the setting and tray availability.
"""
from __future__ import annotations

from dataclasses import dataclass

SHOW = "show"
HIDE = "hide"
MINIMIZE = "minimize"
QUIT = "quit"

LAUNCHER = "launcher"
ACCOUNTS = "accounts"
KEYSETS = "keysets"
SETTINGS = "settings"
ACCOUNT = "account"            # with an account id
CURRENT = "current"            # as it was left: whatever sheet was open stays
TARGETS = (LAUNCHER, ACCOUNTS, KEYSETS, SETTINGS, ACCOUNT, CURRENT)

VISIBLE = "visible"
HIDDEN = "hidden"
MINIMIZED = "minimized"


@dataclass(frozen=True)
class Command:
    kind: str                       # show | hide | minimize | quit
    target: str | None = None       # for show: one of TARGETS
    account_id: str | None = None   # for show with target "account"


class WindowLifecycle:
    def __init__(self, hide_when_toons_up: bool = True, tray_available: bool = True):
        self.hide_when_toons_up = bool(hide_when_toons_up)
        self.tray_available = bool(tray_available)
        self.window = HIDDEN
        self.pending: set = set()
        self.live_windows = 0
        self._batch_landed = False
        self._batch_failed = False

    # ── events ──────────────────────────────────────────────────────────
    def started(self, live_windows: int = 0) -> list[Command]:
        """App start: shown on the launcher."""
        self.live_windows = max(0, int(live_windows))
        return self._show(LAUNCHER)

    def launch_pending(self, key) -> list[Command]:
        """A launch was started (any entry point). The window stays as it is."""
        if not self.pending:
            self._batch_landed = False
            self._batch_failed = False
        self.pending.add(key)
        return []

    def launch_landed(self, key) -> list[Command]:
        """A pending launch's game window is up."""
        if key not in self.pending:
            return []
        self.pending.discard(key)
        self._batch_landed = True
        return self._maybe_end_batch()

    def launch_failed(self, key) -> list[Command]:
        """A pending launch ended without a game window."""
        if key not in self.pending:
            return []
        self.pending.discard(key)
        self._batch_failed = True
        return self._maybe_end_batch()

    def windows(self, live_windows: int) -> list[Command]:
        """The number of live game windows changed."""
        before = self.live_windows
        self.live_windows = max(0, int(live_windows))
        if before > 0 and self.live_windows == 0 and self.window != VISIBLE:
            return self._show(LAUNCHER)
        return []

    def requested(self, target: str = LAUNCHER, account_id: str | None = None
                  ) -> list[Command]:
        """The home block or the tray asked for the window (and a sheet)."""
        if target not in TARGETS:
            target = LAUNCHER
        if target == ACCOUNT and not account_id:
            target = ACCOUNTS
        return self._show(target, account_id if target == ACCOUNT else None,
                          force=True)

    def close_requested(self) -> list[Command]:
        """The user closed the window."""
        if self.live_windows == 0 and not self.pending:
            self.window = HIDDEN
            return [Command(QUIT)]
        return self._hide()

    def setting_changed(self, hide_when_toons_up: bool) -> list[Command]:
        self.hide_when_toons_up = bool(hide_when_toons_up)
        return []

    def observed(self, window: str) -> list[Command]:
        """The window's real state, when something other than these commands
        changed it (the user minimized or restored it). No commands: it only
        keeps the machine's idea of the window true."""
        if window in (VISIBLE, HIDDEN, MINIMIZED):
            self.window = window
        return []

    def tray_changed(self, available: bool) -> list[Command]:
        """Tray availability changed (or the tray icon setting was turned
        off). A window hidden with no tray left to bring it back is
        minimized instead, so it stays reachable from the taskbar."""
        self.tray_available = bool(available)
        if not self.tray_available and self.window == HIDDEN and self.live_windows:
            self.window = MINIMIZED
            return [Command(MINIMIZE)]
        return []

    # ── internals ───────────────────────────────────────────────────────
    def _maybe_end_batch(self) -> list[Command]:
        if self.pending:
            return []                      # not the last one yet
        landed, failed = self._batch_landed, self._batch_failed
        self._batch_landed = self._batch_failed = False
        if landed and not failed and self.hide_when_toons_up and self.window == VISIBLE:
            return self._hide()
        return []

    def _show(self, target: str, account_id: str | None = None,
              force: bool = False) -> list[Command]:
        if self.window == VISIBLE and not force:
            return []
        self.window = VISIBLE
        return [Command(SHOW, target, account_id)]

    def _hide(self) -> list[Command]:
        if self.tray_available:
            if self.window == HIDDEN:
                return []
            self.window = HIDDEN
            return [Command(HIDE)]
        if self.window == MINIMIZED:
            return []
        self.window = MINIMIZED
        return [Command(MINIMIZE)]
