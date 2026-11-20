"""The in-app update flow: what the header chip says and what the update
sheet shows, from the first "a new build is ready" to the hand-over to the
update window.

``UpdateFlow`` holds the state; it draws nothing. The chip and the sheet read
``chip()`` and ``view()`` and call the action methods; the window connects the
update checker and the downloader to it.

States: none, offer, dl (downloading), fail (download paused, or the
installer would not start), ready. "ingame" is not a state: it is how
``ready`` is shown while toons are running.

On Windows installs the update downloads inside the app and is installed by
the update window after a restart. Every other install method keeps its own
update action (terminal, release page, copy command): the chip and the offer
are the same, and "Update now" runs that action instead.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from utils import release_highlights, update_download
from utils.install_method import InstallMethod
from utils.settings_keys import (
    UPDATE_OFFER_SHOWN_VERSION, UPDATE_PENDING_INSTALL, UPDATE_SKIPPED_VERSION,
    WHATS_NEW_SEEN_VERSION,
)

NONE, OFFER, DOWNLOADING, FAILED, READY = "none", "offer", "dl", "fail", "ready"

# Chip kinds, in the design's order.
CHIP_UPDATE = "update"
CHIP_DOWNLOADING = "downloading"
CHIP_RESTART = "restart"
CHIP_PAUSED = "paused"
CHIP_CHECKING = "checking"
CHIP_UP_TO_DATE = "uptodate"
CHIP_CHECK_FAILED = "checkfailed"
CHIP_WHATS_NEW = "whatsnew"

UP_TO_DATE_MS = 2500
CHECK_FAILED_MS = 3000

FAIL_LAUNCH = "launch"

# The keys an installer writes before the app has ever run: a settings file
# holding nothing else belongs to a first run, not to an update.
_INSTALLER_KEYS = frozenset({
    "check_for_updates_at_startup", "keep_alive_enabled",
    "keep_alive_consent_acknowledged", "keep_alive_consent_source",
    "keep_alive_consent_version",
})


def megabytes(count: int) -> str:
    return f"{count / (1024 * 1024):.1f}"


@dataclass(frozen=True)
class Chip:
    kind: str
    label: str
    percent: int = -1          # downloading: 0..100
    clickable: bool = True


@dataclass(frozen=True)
class SheetView:
    """One state of the update sheet, ready to draw. Actions are the names
    of ``UpdateFlow`` methods."""

    key: str                              # offer | dl | fail | ready | ingame
    micro: str
    headline: str
    body: str = ""
    micro_bad: bool = False
    highlights: tuple = ()
    primary: Optional[tuple] = None       # (label, action): the gold button
    secondary: Optional[tuple] = None     # (label, action): the ghost button
    link: Optional[tuple] = None          # (label, action)
    floor_label: str = ""
    floor_tail: str = ""
    fraction: float = 0.0
    floor_bad: bool = False
    crew_present: int = 2
    crew_bad: Optional[int] = None
    hop: bool = False


def is_first_run(settings_manager) -> bool:
    """True when the settings file held nothing of the app's own when this
    run started: a fresh install, not an update of an existing one."""
    loaded = getattr(settings_manager, "loaded_keys", None)
    if loaded is None:
        return False
    return set(loaded) <= _INSTALLER_KEYS


def whats_new_to_show(settings_manager, notes, local_tag: str,
                      first_run: bool):
    """The notes to present on this launch, or None. A first run marks its
    version as seen without showing anything: nothing is new to a new player."""
    if notes is None or not notes or notes.version != local_tag:
        return None
    if settings_manager.get(WHATS_NEW_SEEN_VERSION) == local_tag:
        return None
    if first_run:
        settings_manager.set(WHATS_NEW_SEEN_VERSION, local_tag)
        return None
    return notes


# ── "Next launch" ──────────────────────────────────────────────────────────


def read_pending(settings_manager) -> Optional[dict]:
    raw = settings_manager.get(UPDATE_PENDING_INSTALL)
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("tag") or not data.get("path"):
        return None
    return data


def clear_pending(settings_manager, delete_file: bool = False) -> None:
    pending = read_pending(settings_manager)
    if settings_manager.get(UPDATE_PENDING_INSTALL):
        settings_manager.set(UPDATE_PENDING_INSTALL, "")
    if delete_file and pending:
        try:
            os.unlink(pending["path"])
        except OSError:
            pass


def _is_newer_tag(local_tag: str, remote_tag: str) -> bool:
    from utils.version_compare import is_newer, parse
    local, remote = parse(local_tag), parse(remote_tag)
    if local is None or remote is None:
        return False
    return is_newer(local, 0, remote, 0)


def install_pending_at_startup(settings_manager, *, local_tag: str,
                               start_update_window: Callable[..., bool],
                               app_pid: Optional[int] = None) -> bool:
    """Called before the main window exists. If a downloaded build is waiting
    for "Next launch", hand over to the update window and return True: the
    caller exits. Anything stale (already installed, file gone or wrong size)
    is cleared and startup carries on."""
    pending = read_pending(settings_manager)
    if pending is None:
        if settings_manager.get(UPDATE_PENDING_INSTALL):
            clear_pending(settings_manager)
        return False
    path, tag = str(pending["path"]), str(pending["tag"])
    if not _is_newer_tag(local_tag, tag):
        clear_pending(settings_manager, delete_file=True)     # it is installed
        return False
    size = int(pending.get("size") or 0)
    try:
        actual = os.path.getsize(path)
    except OSError:
        actual = -1
    if actual <= 0 or (size > 0 and actual != size):
        clear_pending(settings_manager)
        return False
    # One attempt per waiting build: a window that will not start must not
    # keep the app from opening on every launch.
    clear_pending(settings_manager)
    try:
        return bool(start_update_window(
            path, app_pid=app_pid or os.getpid(), from_version=local_tag))
    except Exception as error:  # noqa: BLE001
        print(f"[update] could not start the update window: {error}")
        return False


def discard_downloads() -> None:
    """Remove every downloaded installer: nothing is waiting for them."""
    directory = update_download.download_dir()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


# ── The flow ───────────────────────────────────────────────────────────────


class UpdateFlow(QObject):
    changed = Signal()                 # chip or sheet content changed
    sheet_requested = Signal(bool)     # open (True) or hide (False) the update sheet
    quit_requested = Signal()          # the update window is up: the app must go
    recheck_requested = Signal()       # "Couldn't check · Retry" was clicked
    whats_new_requested = Signal()     # the What's new chip was clicked

    def __init__(self, settings_manager, *, install_method: InstallMethod,
                 local_tag: str, downloader=None, run_native_update=None,
                 start_update_window: Optional[Callable[..., bool]] = None,
                 toons_running: Callable[[], bool] = lambda: False, parent=None):
        super().__init__(parent)
        self._sm = settings_manager
        self._method = install_method
        self.local_tag = local_tag
        self._run_native_update = run_native_update
        self._start_update_window = start_update_window
        self._toons_running = toons_running
        self.state = NONE
        self.info: Optional[dict] = None
        self.notes = None
        self.asset: Optional[dict] = None
        self.received = 0
        self.total = 0
        self.fail_reason = ""
        self.installer_path = ""
        self.whats_new = None                 # notes behind the What's new chip
        self._transient: Optional[Chip] = None
        self._manual_check = False
        self._transient_timer = QTimer(self)
        self._transient_timer.setSingleShot(True)
        self._transient_timer.timeout.connect(self._clear_transient)
        self._downloader = downloader
        if downloader is not None:
            downloader.progress.connect(self._on_progress)
            downloader.finished.connect(self._on_downloaded)
            downloader.failed.connect(self._on_download_failed)

    # ── Facts ──────────────────────────────────────────────────────────────

    def managed(self) -> bool:
        """True when this install downloads and installs the update itself."""
        return (self._method == InstallMethod.WINDOWS_INSTALLER
                and self.asset is not None and self._downloader is not None)

    def tag(self) -> str:
        return (self.info or {}).get("tag_name", "")

    def toons_running(self) -> bool:
        try:
            return bool(self._toons_running())
        except Exception:  # noqa: BLE001
            return False

    def fraction(self) -> float:
        total = self.total or int((self.asset or {}).get("size") or 0)
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.received / total))

    def release_url(self) -> str:
        return (self.info or {}).get("html_url", "")

    # ── From the checker ───────────────────────────────────────────────────

    def on_check_started(self, manual: bool) -> None:
        self._manual_check = bool(manual)
        if manual:
            self._transient_timer.stop()
            self._transient = Chip(CHIP_CHECKING, "Checking for updates", clickable=False)
            self.changed.emit()

    def on_update_available(self, info: dict) -> None:
        manual, self._manual_check = self._manual_check, False
        self._clear_transient(emit=False)
        tag = info.get("tag_name", "")
        same = self.info is not None and self.tag() == tag
        if same and self.state in (DOWNLOADING, READY, FAILED):
            self.changed.emit()
            if manual:
                self.sheet_requested.emit(True)
            return
        self.info = dict(info)
        self.notes = release_highlights.from_release_body(info.get("body", ""), tag)
        self.asset = None
        self.received = self.total = 0
        self.installer_path = ""
        if self._method == InstallMethod.WINDOWS_INSTALLER:
            from utils.update_runner import pick_asset
            self.asset = pick_asset(info.get("assets", []), suffix=".exe")
        self.state = OFFER
        if self.managed():
            final, _partial = update_download.asset_paths(self.asset)
            if update_download.file_matches(final, self.asset):
                # Downloaded on an earlier run.
                self.installer_path = final
                self.received = self.total = int(self.asset.get("size") or 0)
                self.state = READY
            else:
                self.received = update_download.partial_size(self.asset)
                self.total = int(self.asset.get("size") or 0)
        self.changed.emit()
        if manual:
            self.sheet_requested.emit(True)
        elif (self._sm.get(UPDATE_OFFER_SHOWN_VERSION) != tag
              and not self.toons_running()):
            # By itself once per version, and never over a running session.
            self._sm.set(UPDATE_OFFER_SHOWN_VERSION, tag)
            self.sheet_requested.emit(True)

    def on_no_update(self) -> None:
        manual, self._manual_check = self._manual_check, False
        if self.state == NONE:
            discard_downloads()
        if manual:
            self._show_transient(Chip(CHIP_UP_TO_DATE, "Up to date", clickable=False),
                                 UP_TO_DATE_MS)

    def on_check_failed(self, _reason: str = "") -> None:
        manual, self._manual_check = self._manual_check, False
        if manual:
            self._show_transient(Chip(CHIP_CHECK_FAILED, "Couldn’t check · Retry"),
                                 CHECK_FAILED_MS)

    def _show_transient(self, chip: Chip, ms: int) -> None:
        self._transient = chip
        self._transient_timer.start(ms)
        self.changed.emit()

    def _clear_transient(self, emit: bool = True) -> None:
        self._transient_timer.stop()
        if self._transient is not None:
            self._transient = None
            if emit:
                self.changed.emit()

    # ── What the chip says ─────────────────────────────────────────────────

    def chip(self) -> Optional[Chip]:
        if self._transient is not None:
            return self._transient
        if self.state == OFFER:
            return Chip(CHIP_UPDATE, "Update ready")
        if self.state == DOWNLOADING:
            return Chip(CHIP_DOWNLOADING, "Downloading", percent=round(self.fraction() * 100))
        if self.state == FAILED:
            return Chip(CHIP_PAUSED, "Update paused")
        if self.state == READY:
            return Chip(CHIP_RESTART, "Restart to update")
        if self.whats_new is not None:
            return Chip(CHIP_WHATS_NEW, "What’s new")
        return None

    def chip_clicked(self) -> None:
        chip = self.chip()
        if chip is None or not chip.clickable:
            return
        if chip.kind == CHIP_CHECK_FAILED:
            self._clear_transient(emit=False)
            self.recheck_requested.emit()
        elif chip.kind == CHIP_WHATS_NEW:
            self.whats_new_requested.emit()
        else:
            self.sheet_requested.emit(True)

    # ── What the sheet shows ───────────────────────────────────────────────

    def view(self) -> Optional[SheetView]:
        if self.state == NONE or self.info is None:
            return None
        tag = self.tag()
        size = int((self.asset or {}).get("size") or 0)
        size_mb = megabytes(size) if size else ""
        if self.state == OFFER:
            highlights = tuple(h.title for h in self.notes.highlights) if self.notes else ()
            return SheetView(
                key="offer",
                micro=f"Update · {self.local_tag} → {tag}",
                headline="A new build is ready.",
                body="" if highlights else "The full notes are on the release page.",
                highlights=highlights,
                primary=("Update now", "update_now"),
                secondary=("Later", "later"),
                link=("Skip this version", "skip"),
                floor_label=self._offer_floor(size_mb),
                fraction=0.0)
        if self.state == DOWNLOADING:
            return SheetView(
                key="dl", micro=f"Downloading {tag}", headline="Getting it ready.",
                body="Keep playing. Nothing changes until you restart.",
                secondary=("Hide", "later"),
                floor_label=f"Downloading · {megabytes(self.received)} of {size_mb} MB",
                floor_tail=f"{round(self.fraction() * 100)}%",
                fraction=self.fraction())
        if self.state == FAILED:
            if self.fail_reason == FAIL_LAUNCH:
                return SheetView(
                    key="fail", micro="Update paused", micro_bad=True,
                    headline="The installer didn’t start.",
                    body="The download is kept. Try again, or install it the next "
                         "time you open MultiTool.",
                    primary=("Try again", "restart_now"), secondary=("Later", "later"),
                    floor_label=f"Downloaded · {size_mb} MB", fraction=1.0,
                    floor_bad=True, crew_present=1, crew_bad=1)
            if self.fail_reason.startswith(update_download.REASON_NETWORK):
                headline = "Lost the connection."
                body = "What’s downloaded is kept, so it picks up where it stopped."
            elif self.fail_reason.startswith(update_download.REASON_DISK):
                headline = "Couldn’t save the download."
                body = "Check that there is free space on this drive, then try again."
            else:
                headline = "The download was damaged."
                body = "It didn’t match the release, so it was thrown away. " \
                       "Trying again starts over."
            return SheetView(
                key="fail", micro="Download paused", micro_bad=True,
                headline=headline, body=body,
                primary=("Try again", "try_again"), secondary=("Later", "later"),
                floor_label=f"Paused · {megabytes(self.received)} of {size_mb} MB",
                fraction=self.fraction(), floor_bad=True, crew_present=1, crew_bad=1)
        # READY
        floor = f"Downloaded · {size_mb} MB"
        if self.toons_running():
            return SheetView(
                key="ingame", micro=f"Ready · {tag}",
                headline="Your toons are still in game.",
                body="Restarting closes MultiTool for a moment. Game windows stay open, "
                     "but multitoon input and Keep-Alive stop until it’s back.",
                primary=("Next launch", "next_launch"),
                secondary=("Restart anyway", "restart_now"),
                floor_label=floor, fraction=1.0)
        return SheetView(
            key="ready", micro=f"Ready · {tag}", headline="Restart to finish.",
            body="The app closes while the installer runs, then reopens on its own.",
            primary=("Restart & update", "restart_now"),
            secondary=("Next launch", "next_launch"),
            floor_label=floor, fraction=1.0, hop=True)

    def _offer_floor(self, size_mb: str) -> str:
        if self.managed():
            return f"{size_mb} MB · installs after a restart"
        return {
            InstallMethod.APPIMAGE: "Opens the release page",
            InstallMethod.FLATPAK: "Installs in a terminal, then restarts",
            InstallMethod.DEB: "Installs in a terminal, then restarts",
            InstallMethod.AUR: "Updates through your AUR helper",
            InstallMethod.SOURCE: "Shows the command to run",
            InstallMethod.WINDOWS_INSTALLER: "Opens the release page",
        }.get(self._method, "")

    # ── Actions ────────────────────────────────────────────────────────────

    def update_now(self) -> None:
        if self.state != OFFER or self.info is None:
            return
        if not self.managed():
            # This install method has its own update action.
            self.sheet_requested.emit(False)
            if self._run_native_update is not None:
                self._run_native_update(self.info)
            return
        self._begin_download()

    def try_again(self) -> None:
        if self.state == FAILED and self.asset is not None:
            self._begin_download()

    def _begin_download(self) -> None:
        self.fail_reason = ""
        self.state = DOWNLOADING
        self.received = update_download.partial_size(self.asset)
        self.total = int(self.asset.get("size") or 0)
        self.changed.emit()
        if not self._downloader.start(self.asset):
            self.changed.emit()

    def later(self) -> None:
        """Later, Hide and the scrim: the sheet goes, the chip stays."""
        self.sheet_requested.emit(False)

    def skip(self) -> None:
        if self.info is None:
            return
        self._sm.set(UPDATE_SKIPPED_VERSION, self.tag())
        if self.asset is not None:
            update_download.discard(self.asset)
        self.state = NONE
        self.info = None
        self.asset = None
        self.sheet_requested.emit(False)
        self.changed.emit()

    def restart_now(self) -> None:
        """Restart & update, Restart anyway: hand over to the update window
        and quit. No further confirmation."""
        if self.state not in (READY, FAILED) or not self.installer_path:
            return
        started = False
        if self._start_update_window is not None:
            try:
                started = bool(self._start_update_window(
                    self.installer_path, app_pid=os.getpid(), from_version=self.local_tag))
            except Exception as error:  # noqa: BLE001
                print(f"[update] could not start the update window: {error}")
        if not started:
            self.state = FAILED
            self.fail_reason = FAIL_LAUNCH
            self.changed.emit()
            self.sheet_requested.emit(True)
            return
        clear_pending(self._sm)
        self.sheet_requested.emit(False)
        self.quit_requested.emit()

    def next_launch(self) -> None:
        """Install the downloaded build the next time the app starts."""
        if self.state != READY or not self.installer_path:
            return
        self._sm.set(UPDATE_PENDING_INSTALL, json.dumps({
            "tag": self.tag(), "path": self.installer_path,
            "size": int((self.asset or {}).get("size") or 0)}))
        self.sheet_requested.emit(False)

    # ── From the downloader ────────────────────────────────────────────────

    def _on_progress(self, received: int, total: int) -> None:
        if self.state != DOWNLOADING:
            return
        self.received = received
        if total > 0:
            self.total = total
        self.changed.emit()

    def _on_downloaded(self, path: str) -> None:
        if self.state != DOWNLOADING:
            return
        self.installer_path = path
        self.received = self.total = int((self.asset or {}).get("size") or self.received)
        self.state = READY
        self.changed.emit()
        if not self.toons_running():
            # Ready and nobody is playing: say so. Otherwise the chip turns
            # green and waits.
            self.sheet_requested.emit(True)

    def _on_download_failed(self, reason: str) -> None:
        if self.state != DOWNLOADING:
            return
        self.fail_reason = reason or update_download.REASON_NETWORK
        self.received = update_download.partial_size(self.asset) if self.asset else 0
        self.state = FAILED
        self.changed.emit()

    # ── What's new ─────────────────────────────────────────────────────────

    def mark_whats_new_seen(self, notes) -> None:
        """The What's new sheet was shown: remember it, and keep the chip for
        the rest of the session."""
        self._sm.set(WHATS_NEW_SEEN_VERSION, self.local_tag)
        self.whats_new = notes
        self.changed.emit()

    def shutdown(self) -> None:
        if self._downloader is not None:
            self._downloader.shutdown()
