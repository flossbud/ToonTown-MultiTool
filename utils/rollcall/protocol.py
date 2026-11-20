"""The protocol between Setup (packaging/windows/installer.iss) and Roll Call.

Standard library only: the running app imports this (through handoff.py)
to start the update window, and it must not drag Qt or anything else in.

Setup flags (Inno parses ``/NAME=value``; values cannot contain a double
quote, and a backslash before a quote is not an escape):

    /RCPROGRESS=<file>   a window-driven silent run: append events to <file>,
                         honour <file>.pause and <file>.cancel
    /RCMODE=update /RCPID=<pid> /RCFROM=<tag> /RCREADY=<file>
                         start the update window (the app passes these)
    /RCARGS=<text>       appended to the window's command line (tests)
    /RCLOG=<file>        the window's log file (default %TEMP%\\ttmt-rollcall.log)
    /RCWIZARD            the stock wizard, never the window
    /RCTESTFAIL=<permille>
                         stop the file copy with an error at that point (tests)

Progress lines, one event per line, written only by Setup:

    hello <pid> <version> <build> <yes|no admin mode | uninstall>
    step <n>             0 unpacking, 1 copying files, 2 shortcuts and registry
    progress <permille>  file copy, 0..1000 of everything Setup installs
    backup ok <dir> | backup none
    paused | resumed
    cancelled <where>    a stop the window asked for was honoured
    error <what> [...]   backup in-use | test-failure | restore
    restored <dir>       the previous version is back after a failed run
    installed            Setup's part is done (ssPostInstall)
    removing | removed   uninstaller
    end                  Setup is exiting
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# rollcall.exe exit codes (utils/rollcall/app.py); Setup passes them on.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANCELLED = 2
EXIT_NO_WINDOW = 3          # Setup falls back to its wizard (installer.iss RC_EXIT_NO_WINDOW)

# Inno Setup exit codes this protocol relies on (checked in Inno's source).
SETUP_OK = 0
SETUP_CANCELLED_BEFORE_INSTALL = 2   # also: the UAC prompt was declined
SETUP_INSTALL_ABORTED = 5            # cancel, or a file error answered "Abort"

PAUSE_SUFFIX = ".pause"
CANCEL_SUFFIX = ".cancel"

READY_UP = "up"                 # the window is on screen (update: the app may quit)
READY_NO_WINDOW = "no-window"   # Setup could not show the update window

BACKUP_SUFFIX = ".previous-version"
TRASH_SUFFIX = ".removing"

APP_EXE = "ToonTownMultiTool.exe"


def quote_arg(arg: str) -> str:
    """One argument for Inno's command-line parser, which toggles on double
    quotes and knows no escapes. A trailing backslash is dropped from a
    quoted value (it would escape the closing quote for the C runtime)."""
    if '"' in arg:
        raise ValueError(f"a Setup argument cannot contain a double quote: {arg!r}")
    if arg and not any(ch.isspace() for ch in arg):
        return arg
    return '"' + arg.rstrip("\\") + '"'


def command_line(exe: str, args) -> str:
    return " ".join([quote_arg(exe)] + [quote_arg(a) for a in args])


@dataclass
class RunState:
    """What the progress lines of one Setup run said so far."""

    hello: bool = False
    admin_mode: bool = False
    step: int = -1
    permille: int = 0
    backup: str = ""            # "" unknown | "none" | "ok"
    backup_dir: str = ""
    paused: bool = False
    cancelled: bool = False
    restored: bool = False
    installed: bool = False
    removing: bool = False
    removed: bool = False
    ended: bool = False
    errors: list = field(default_factory=list)   # the words after "error"

    def apply(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        word, _, rest = line.partition(" ")
        if word == "hello":
            self.hello = True
            parts = rest.split()
            self.admin_mode = bool(parts) and parts[-1] == "yes"
        elif word == "step":
            try:
                self.step = max(self.step, int(rest.split()[0]))
            except (ValueError, IndexError):
                pass
        elif word == "progress":
            try:
                self.permille = max(0, min(1000, int(rest.split()[0])))
            except (ValueError, IndexError):
                pass
        elif word == "backup":
            kind, _, where = rest.partition(" ")
            self.backup = kind
            self.backup_dir = where
        elif word == "paused":
            self.paused = True
        elif word == "resumed":
            self.paused = False
        elif word == "cancelled":
            self.cancelled = True
        elif word == "restored":
            self.restored = True
        elif word == "installed":
            self.installed = True
        elif word == "removing":
            self.removing = True
        elif word == "removed":
            self.removed = True
        elif word == "end":
            self.ended = True
        elif word == "error":
            self.errors.append(rest)

    def has_error(self, prefix: str) -> bool:
        return any(e == prefix or e.startswith(prefix + " ") for e in self.errors)


class LineReader:
    """Reads the lines a file gained since the last call. Setup opens the
    file exclusively for each line it appends, so a read that collides with
    a write just returns nothing this time."""

    def __init__(self, path: str):
        self.path = path
        self._offset = 0
        self._partial = b""

    def read(self) -> list:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        self._offset += len(data)
        data = self._partial + data
        *complete, self._partial = data.split(b"\n")
        return [chunk.rstrip(b"\r").decode("utf-8", "replace") for chunk in complete]


def write_ready(path: str, word: str) -> bool:
    if not path:
        return False
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(word + "\n")
        return True
    except OSError:
        return False


def read_ready(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def touch(path: str) -> None:
    try:
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError:
        pass


def remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
