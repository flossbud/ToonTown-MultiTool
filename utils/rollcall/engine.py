"""What the Roll Call windows ask of the machine.

The windows (installer, update window, uninstaller) only draw and decide what
to show. Everything that touches the PC goes through an ``Engine``: finding an
existing install, running Setup without its wizard, closing and reopening the
app, removing it. ``FakeEngine`` plays a run on a timer for the render harness,
the tests and ``--demo``; the real one lives in ``engine_inno``.

Progress is reported per step. A step that cannot measure itself reports
``INDETERMINATE`` and the window eases its stripe along on its own; a step is
over when the next one reports, or when the run finishes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal

INSTALL_STEPS = ("Unpacking", "Copying files", "Creating shortcuts", "Saving your choices")
UPDATE_STEPS = ("Closing the app", "Installing", "Reopening")
REMOVE_STEPS = ("Closing the app", "Removing files", "Removing shortcuts", "Cleaning up")

INDETERMINATE = -1.0


@dataclass(frozen=True)
class Flavor:
    """The build this Setup carries. Every name and path the windows show
    comes from here: stable and beta differ in all of them."""

    app_name: str = "ToonTown MultiTool"
    version: str = "vDEV"                 # the release tag, with its v
    build: int = 0
    app_id: str = ""
    config_dir_name: str = "toontown_multitool"
    channel: str = "stable"               # "stable" | "beta"
    payload_bytes: int = 0                # installed size; 0 = unknown, not shown

    @property
    def short_name(self) -> str:
        return "MultiTool Beta" if self.channel == "beta" else "MultiTool"


@dataclass(frozen=True)
class Installed:
    """An install of this flavor already on the PC."""

    version: str            # tag as recorded by its installer, e.g. "v0.8.0-alpha.1"
    build: int              # 0 when unknown
    directory: str
    all_users: bool


@dataclass(frozen=True)
class InstallOptions:
    directory: str
    desktop_shortcut: bool = True
    start_menu: bool = True
    check_updates: bool = True
    keep_alive: bool = False    # True only after the consent block was accepted

    def with_(self, **changes) -> "InstallOptions":
        return replace(self, **changes)


@dataclass(frozen=True)
class Failure:
    """A run that stopped. ``step`` is the step that failed (its toon stays
    away). ``headline`` and ``body`` are shown as they are; ``detail`` is the
    raw error line ("Access is denied · 0x80070005")."""

    step: int
    headline: str
    body: str
    detail: str = ""
    log_path: str = ""
    previous_intact: bool = True    # update / repair: the old version still runs

    def details_text(self, step_label: str) -> str:
        """What Copy details puts on the clipboard."""
        lines = [f"Step: {step_label}", f"Error: {self.detail or self.headline}"]
        if self.log_path:
            lines.append(f"Log: {self.log_path}")
        return "\n".join(lines)


class Engine(QObject):
    """The contract. Every start method returns at once; the run reports
    through the signals, on the GUI thread."""

    step_progress = Signal(int, float)   # step index, 0..1 of that step or INDETERMINATE
    finished = Signal()                  # every step done
    failed = Signal(object)              # Failure
    cancelled = Signal()                 # stopped and undone; also a declined elevation prompt
    app_closed = Signal(bool)            # answer to close_app()

    # ── What is there ──────────────────────────────────────────────────────

    def flavor(self) -> Flavor:
        raise NotImplementedError

    def installed(self) -> Installed | None:
        """The existing install of this flavor, or None."""
        raise NotImplementedError

    def default_options(self) -> InstallOptions:
        """Where and how a plain Install click installs. Over an existing
        install: its directory."""
        raise NotImplementedError

    def config_dir_display(self) -> str:
        """The user-data directory as shown to the player, unexpanded where
        that is shorter (``%USERPROFILE%\\.config\\toontown_multitool``)."""
        raise NotImplementedError

    def previous_version(self) -> str:
        """Update mode: the tag the app is being updated from ("" if unknown)."""
        return ""

    def app_running(self) -> bool:
        raise NotImplementedError

    # ── Runs ───────────────────────────────────────────────────────────────

    def close_app(self) -> None:
        """Ask the running app to quit; ``app_closed`` answers."""
        raise NotImplementedError

    def install(self, options: InstallOptions) -> None:
        """Steps: INSTALL_STEPS. Ends in finished, failed or cancelled."""
        raise NotImplementedError

    def can_cancel(self) -> bool:
        """Whether the run in flight can still be stopped and undone."""
        return False

    def set_paused(self, paused: bool) -> None:
        """Hold the run in place while the player decides whether to stop."""

    def cancel(self) -> None:
        """Stop the run and undo it; ``cancelled`` when the PC is as it was."""
        raise NotImplementedError

    def update(self) -> None:
        """Steps: UPDATE_STEPS. Waits for the app to exit, installs, reopens
        it; finished once the app's window is on screen. A failure leaves the
        previous version in place."""
        raise NotImplementedError

    def uninstall(self, remove_user_data: bool) -> None:
        """Steps: REMOVE_STEPS. Cannot be cancelled."""
        raise NotImplementedError

    def open_app(self) -> bool:
        """Start the installed app. False if it could not be started."""
        raise NotImplementedError

    def open_uninstaller(self) -> bool:
        """Installer, "Uninstall instead": hand over to the uninstall window."""
        return False


class FakeEngine(Engine):
    """A run on a timer. ``fail_at`` (a step index) stops the run there;
    ``running`` starts with the app open; ``installed`` plants an install."""

    TICK_MS = 30

    def __init__(self, *, flavor: Flavor | None = None, installed: Installed | None = None,
                 running: bool = False, fail_at: int | None = None,
                 duration_ms: int = 7500, previous_version: str = "", parent=None):
        super().__init__(parent)
        self._flavor = flavor or Flavor(version="v0.8.0-alpha.2", build=412,
                                        payload_bytes=88_300_000)
        self._installed = installed
        self._running = running
        self._fail_at = fail_at
        self._duration = max(1, duration_ms)
        self._previous = previous_version
        self._steps = 0
        self._elapsed = 0.0
        self._paused = False
        self._kind = ""
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.opened = 0
        self.last_options: InstallOptions | None = None
        self.removed_user_data: bool | None = None

    # ── What is there ──────────────────────────────────────────────────────

    def flavor(self) -> Flavor:
        return self._flavor

    def installed(self) -> Installed | None:
        return self._installed

    def default_options(self) -> InstallOptions:
        if self._installed is not None:
            return InstallOptions(directory=self._installed.directory)
        return InstallOptions(
            directory="C:\\Users\\Flossbud\\AppData\\Local\\Programs\\" + self._flavor.app_name)

    def config_dir_display(self) -> str:
        return "%USERPROFILE%\\.config\\" + self._flavor.config_dir_name

    def previous_version(self) -> str:
        return self._previous

    def app_running(self) -> bool:
        return self._running

    # ── Runs ───────────────────────────────────────────────────────────────

    def close_app(self) -> None:
        self._running = False
        QTimer.singleShot(0, lambda: self.app_closed.emit(True))

    def install(self, options: InstallOptions) -> None:
        self.last_options = options
        self._begin("install", len(INSTALL_STEPS))

    def can_cancel(self) -> bool:
        return self._kind == "install" and (self._timer.isActive() or self._paused)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    def cancel(self) -> None:
        self._timer.stop()
        self._paused = False
        QTimer.singleShot(0, self.cancelled.emit)

    def update(self) -> None:
        self._begin("update", len(UPDATE_STEPS))

    def uninstall(self, remove_user_data: bool) -> None:
        self.removed_user_data = bool(remove_user_data)
        self._begin("uninstall", len(REMOVE_STEPS))

    def open_app(self) -> bool:
        self.opened += 1
        return True

    # ── The clock ──────────────────────────────────────────────────────────

    def _begin(self, kind: str, steps: int) -> None:
        self._kind = kind
        self._steps = steps
        self._elapsed = 0.0
        self._paused = False
        self.step_progress.emit(0, 0.0)
        self._timer.start()

    def set_fail_at(self, step: int | None) -> None:
        self._fail_at = step

    def _tick(self) -> None:
        if self._paused:
            return
        self._elapsed += self.TICK_MS
        overall = min(1.0, self._elapsed / self._duration)
        step = min(self._steps - 1, int(overall * self._steps))
        within = overall * self._steps - step
        if self._fail_at is not None and (step > self._fail_at or (
                step == self._fail_at and within >= 0.6)):
            self._timer.stop()
            self.failed.emit(Failure(
                step=self._fail_at,
                headline="Couldn\u2019t copy the files.",
                body="Windows blocked writing to the install folder. "
                     "Anything already copied was removed.",
                detail="Access is denied \u00b7 0x80070005",
                log_path="C:\\Users\\Flossbud\\AppData\\Local\\Temp\\ttmt-setup.log"))
            return
        if overall >= 1.0:
            self._timer.stop()
            if self._kind in ("install", "update"):
                self._installed = Installed(
                    self._flavor.version, self._flavor.build,
                    self.default_options().directory, False)
            else:
                self._installed = None
            self.finished.emit()
            return
        self.step_progress.emit(step, min(1.0, within))
