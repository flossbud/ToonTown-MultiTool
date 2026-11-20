"""The installer window (frames A1 to A5): one click to install, the old
wizard's choices behind Customize, and the four toons as the progress bar.

States: idle (fresh install, or an update over an older one), newer (this
Setup is older than what is installed), maint (this version is installed),
busy (the app is running), run, ask (paused on Cancel), stopping, undone,
fail, done.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from utils.rollcall import motion
from utils.rollcall import tokens as T
from utils.rollcall.controls import RcButton, RcLink
from utils.rollcall.engine import INSTALL_STEPS, Engine, Failure, Installed
from utils.rollcall.panel import CustomizePanel
from utils.rollcall.stage import (
    Actions, Body, ErrorLine, Headline, Link, Meta, Micro, Percent,
)
from utils.rollcall.window import RollcallWindow

FRESH, UPGRADE, SAME, NEWER = "fresh", "upgrade", "same", "newer"


def relation(installed: Installed | None, version: str, build: int) -> str:
    """How this Setup's build relates to what is installed."""
    if installed is None:
        return FRESH
    if installed.build > 0 and build > 0:
        if installed.build == build:
            return SAME
        return UPGRADE if build > installed.build else NEWER
    if installed.version == version:
        return SAME
    try:
        from utils.version_compare import is_newer, parse
        mine, theirs = parse(version), parse(installed.version)
        if mine is not None and theirs is not None:
            if is_newer(theirs, 0, mine, 0):
                return UPGRADE
            if is_newer(mine, 0, theirs, 0):
                return NEWER
            return SAME
    except Exception:  # noqa: BLE001
        pass
    return UPGRADE


def size_text(payload_bytes: int) -> str:
    if payload_bytes <= 0:
        return ""
    return f"{payload_bytes / (1024 * 1024):.1f} MB"


class InstallerWindow(RollcallWindow):
    state_changed = Signal(str)

    def __init__(self, engine: Engine):
        self.engine = engine
        self.flavor = engine.flavor()
        super().__init__(T.LARGE, f"{self.flavor.app_name} Setup")
        self.state = ""
        self._installed = engine.installed()
        self._relation = relation(self._installed, self.flavor.version, self.flavor.build)
        self._follower = motion.RunFollower(len(INSTALL_STEPS))
        self._failure: Failure | None = None
        self._retry_from = 0
        self._shown_step = -1
        self._return_state = "idle"
        self._cancel_link: RcLink | None = None
        self._copy_link: RcLink | None = None

        self.panel = CustomizePanel(self.stage, engine.default_options(), T.LARGE.radius)
        self.panel.done.connect(lambda: self.panel.set_open(False))
        self.panel.change_location.connect(self._choose_directory)
        self.panel.changed.connect(self._on_options_changed)

        self.stage.set_steps(INSTALL_STEPS)
        engine.step_progress.connect(self._on_progress)
        engine.finished.connect(self._on_finished)
        engine.failed.connect(self._on_failed)
        engine.cancelled.connect(self._on_cancelled)
        engine.app_closed.connect(self._on_app_closed)

        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self._refresh_run)

        self._enter_first()

    # ── Small builders ─────────────────────────────────────────────────────

    def _gold(self, text: str, slot, icon: str = "") -> RcButton:
        button = RcButton.gold(text, self.variant, icon=icon)
        button.clicked.connect(slot)
        return button

    def _ghost(self, text: str, slot) -> RcButton:
        button = RcButton.ghost(text, self.variant)
        button.clicked.connect(slot)
        return button

    def _link(self, text: str, slot) -> RcLink:
        link = RcLink(text)
        link.clicked.connect(slot)
        return link

    def _set(self, state: str, items: list, animate: bool = True) -> None:
        self.state = state
        self._cancel_link = None
        self._copy_link = None
        self.stage.copy.set_items(items, animate=animate)
        self.state_changed.emit(state)

    def _version_pair(self) -> str:
        old = self._installed.version if self._installed else ""
        return f"{old} → {self.flavor.version}" if old else self.flavor.version

    # ── States ─────────────────────────────────────────────────────────────

    def _enter_first(self) -> None:
        if self._relation == SAME:
            self._enter_maint(animate=False)
        elif self._relation == NEWER:
            self._enter_newer(animate=False)
        else:
            self._enter_idle(animate=False)

    def _enter_idle(self, animate: bool = True) -> None:
        self._return_state = "idle"
        self.stage.set_steps(INSTALL_STEPS)
        self.stage.set_crew(4, 0, animate=animate)
        upgrade = self._relation == UPGRADE
        options = self.panel.options()
        size = size_text(self.flavor.payload_bytes)
        lead = f"{size} · " if size else ""
        if upgrade:
            items = [
                Micro(f"Update · {self._version_pair()}"),
                Headline("Control four toons at once."),
                Body("The multitoon controller for Toontown Rewritten and Corporate Clash."),
                Actions([self._gold("Update", self._on_install, icon="down")]),
                Meta(lead, options.directory),
            ]
        else:
            items = [
                Micro(f"Windows · {self.flavor.version}"),
                Headline("Control four toons at once."),
                Body("The multitoon controller for Toontown Rewritten and Corporate Clash."),
                Actions([self._gold("Install", self._on_install, icon="down"),
                         self._ghost("Customize", self._toggle_panel)]),
                Meta(lead, options.directory),
            ]
        self._set("idle", items, animate)

    def _enter_newer(self, animate: bool = True) -> None:
        self._return_state = "newer"
        self.stage.set_steps(INSTALL_STEPS)
        self.stage.set_all_done()
        self.stage.set_crew(4, 4, animate=animate)
        installed = self._installed.version if self._installed else ""
        self._set("newer", [
            Micro(f"Installed · {installed}"),
            Headline("A newer build is already here.", md=True),
            Body(f"This installer is {self.flavor.version}. Installing it would take "
                 f"you back from {installed}."),
            Actions([self._gold("Open", self._on_open, icon="play"),
                     self._ghost("Install anyway", self._on_install)]),
        ], animate)

    def _enter_maint(self, animate: bool = True) -> None:
        self._return_state = "maint"
        self.stage.set_steps(INSTALL_STEPS)
        self.stage.set_all_done()
        self.stage.set_crew(4, 4, animate=animate)
        self._set("maint", [
            Micro(f"Already installed · {self.flavor.version}"),
            Headline("Everyone’s already here."),
            Body("This version is installed. Repair it if something looks broken."),
            Actions([self._gold("Open", self._on_open, icon="play"),
                     self._ghost("Repair", self._on_install)]),
            Link(self._link("Uninstall instead", self._on_uninstall_instead)),
        ], animate)

    def _enter_busy(self, problem: bool = False) -> None:
        short = self.flavor.short_name
        self.stage.set_steps(INSTALL_STEPS)
        self.stage.set_crew(4, 0)
        self._set("busy", [
            Micro("Couldn’t close it" if problem else "Before installing", bad=problem),
            Headline(f"{short} is still running.", md=True),
            Body("Close it to continue. Your game windows stay open; multitoon input "
                 "pauses until it’s back."),
            Actions([self._gold("Close & install", self._on_close_and_install),
                     self._ghost("Cancel", self._back_from_busy)]),
        ])

    def _enter_run(self) -> None:
        self.panel.set_open(False)
        self._failure = None
        self._shown_step = -1
        self.stage.set_steps(INSTALL_STEPS)
        self._follower.reset(keep_before=self._retry_from)
        self.stage.follow(self._follower)
        # Toon n takes its place as step n starts.
        self.stage.set_crew(4, self._retry_from + 1)
        self._show_run_copy()
        self._ticker.start()
        self.engine.install(self.panel.options())

    def _run_word(self) -> str:
        return "Updating" if self._relation == UPGRADE else "Installing"

    def _show_run_copy(self, animate: bool = True) -> None:
        step = self._follower.step
        items = [
            Micro(f"{self._run_word()} · step {step + 1} of 4"),
            Headline(INSTALL_STEPS[step], md=True),
            Percent(self._percent()),
            Body("Your toons are taking their places."),
        ]
        link = self._link("Cancel", self._on_cancel_link)
        items.append(Link(link))
        self._set("run", items, animate)
        self._cancel_link = link
        self._shown_step = step
        link.setVisible(self.engine.can_cancel())

    def _percent(self) -> str:
        return f"{round(self._follower.overall() * 100)}%"

    def _enter_ask(self) -> None:
        self.engine.set_paused(True)
        self._follower.held = True
        step = self._follower.step
        self._set("ask", [
            Micro(f"Paused · step {step + 1} of 4"),
            Headline(f"Stop {self._run_word().lower()}?", md=True),
            Body("Anything copied so far is removed."),
            Actions([self._gold("Keep going", self._on_keep_going),
                     self._ghost("Stop", self._on_stop)]),
        ])

    def _enter_stopping(self) -> None:
        self._ticker.stop()
        self.stage.follow(None)
        self.stage.set_fractions([0.0] * 4)
        self.stage.set_crew(4, 0)
        self._set("stopping", [
            Micro("Cancelling"),
            Headline("Putting things back.", md=True),
            Body("This takes a moment."),
        ])

    def _enter_undone(self) -> None:
        self._ticker.stop()
        self._retry_from = 0
        self.stage.follow(None)
        self.stage.set_steps(INSTALL_STEPS)
        self.stage.set_crew(4, 0)
        nothing = ("Nothing was changed." if self._installed is not None
                   else "Nothing was installed.")
        self._set("undone", [
            Micro("Cancelled"),
            Headline(nothing, md=True),
            Body("Your PC is exactly as it was."),
            Actions([self._ghost("Close", self.close_now)]),
            Link(self._link("Start over", self._on_start_over)),
        ])

    def _enter_fail(self, failure: Failure) -> None:
        self._ticker.stop()
        self._failure = failure
        step = max(0, min(3, failure.step))
        self._retry_from = step
        fractions = list(self._follower.shown)
        self.stage.follow(None)
        self.stage.set_fractions(
            [1.0 if i < step else (max(fractions[i], 0.08) if i == step else 0.0)
             for i in range(4)])
        self.stage.set_failed(step)
        self.stage.set_crew(4, step, bad=step)
        buttons = [self._gold("Try again", self._on_install)]
        if self._installed is None:
            buttons.append(self._ghost("Change location", self._on_change_location))
        items = [
            Micro(f"Stopped at step {step + 1} of 4", bad=True),
            Headline(failure.headline, md=True),
            Body(failure.body),
        ]
        if failure.detail:
            items.append(ErrorLine(failure.detail))
        items.append(Actions(buttons))
        link = self._link("Copy details", self._on_copy_details)
        items.append(Link(link))
        self._set("fail", items)
        self._copy_link = link

    def _enter_done(self) -> None:
        self._ticker.stop()
        self._retry_from = 0
        self._installed = self.engine.installed() or self._installed
        self._follower.fill()
        self.stage.set_all_done()
        self.stage.set_crew(4, 4)
        word = "Updated" if self._relation == UPGRADE else "Installed"
        self._set("done", [
            Micro(f"{word} · {self.flavor.version}"),
            Headline("Everyone’s here."),
            Body("Add your accounts in the Launcher and you’re ready to play."),
            Actions([self._gold(f"Open {self.flavor.short_name}", self._on_open, icon="play"),
                     self._ghost("Close", self.close_now)]),
        ])
        # The hop starts once the last toon has landed.
        QTimer.singleShot(T.TOON_MOVE_MS, self.stage.hop)

    # ── Events ─────────────────────────────────────────────────────────────

    def _toggle_panel(self) -> None:
        self.panel.set_open(not self.panel.is_open())

    def _on_change_location(self) -> None:
        self.panel.set_open(True)

    def _on_options_changed(self) -> None:
        if self.state == "idle":
            self._enter_idle(animate=False)

    def _choose_directory(self) -> None:
        current = self.panel.options().directory
        chosen = QFileDialog.getExistingDirectory(self, "Install location", current)
        if not chosen:
            return
        chosen = chosen.replace("/", "\\").rstrip("\\")
        name = self.flavor.app_name
        if chosen.rsplit("\\", 1)[-1].lower() != name.lower():
            chosen = f"{chosen}\\{name}"
        self.panel.set_directory(chosen)

    def _on_install(self) -> None:
        if self.state in ("run", "ask", "stopping"):
            return
        if self.engine.app_running():
            self.panel.set_open(False)
            self._enter_busy()
            return
        self._enter_run()

    def _on_close_and_install(self) -> None:
        for control in self.stage.copy.controls():
            control.setEnabled(False)
        self.engine.close_app()

    def _on_app_closed(self, closed: bool) -> None:
        if self.state != "busy":
            return
        if closed:
            self._enter_run()
        else:
            self._enter_busy(problem=True)

    def _back_from_busy(self) -> None:
        if self._failure is not None:
            self._enter_fail(self._failure)
        elif self._return_state == "maint":
            self._enter_maint()
        elif self._return_state == "newer":
            self._enter_newer()
        else:
            self._enter_idle()

    def _on_progress(self, step: int, fraction: float) -> None:
        if self.state not in ("run", "ask"):
            return
        self._follower.report(step, fraction)
        if self.state == "run":
            self._sync_step()

    def _sync_step(self) -> None:
        step = self._follower.step
        if step != self._shown_step:
            self._shown_step = step
            self.stage.copy.set_micro(f"{self._run_word()} · step {step + 1} of 4")
            self.stage.copy.set_headline(INSTALL_STEPS[step])
            self.stage.set_crew(4, step + 1)
        if self._cancel_link is not None:
            self._cancel_link.setVisible(self.engine.can_cancel())

    def _refresh_run(self) -> None:
        if self.state == "run":
            self.stage.copy.set_percent(self._percent())

    def _on_cancel_link(self) -> None:
        if self.state == "run" and self.engine.can_cancel():
            self._enter_ask()

    def _on_keep_going(self) -> None:
        self.engine.set_paused(False)
        self._follower.held = False
        self._show_run_copy()
        self.stage.follow(self._follower)

    def _on_stop(self) -> None:
        self._enter_stopping()
        self.engine.cancel()

    def _on_cancelled(self) -> None:
        if self.state in ("run", "ask", "stopping"):
            self._enter_undone()

    def _on_failed(self, failure: Failure) -> None:
        if self.state in ("run", "ask", "stopping"):
            self._enter_fail(failure)

    def _on_finished(self) -> None:
        if self.state in ("run", "ask"):
            self._enter_done()

    def _on_start_over(self) -> None:
        self._failure = None
        self._installed = self.engine.installed()
        self._relation = relation(self._installed, self.flavor.version, self.flavor.build)
        self._enter_first()

    def _on_copy_details(self) -> None:
        if self._failure is None:
            return
        label = INSTALL_STEPS[max(0, min(3, self._failure.step))]
        QGuiApplication.clipboard().setText(self._failure.details_text(label))
        link = self._copy_link
        if link is not None:
            link.set_label("Copied")

    def _on_open(self) -> None:
        self.engine.open_app()
        self.close_now()

    def _on_uninstall_instead(self) -> None:
        if self.engine.open_uninstaller():
            self.close_now()

    # The red light, Alt+F4 and Esc behave like the Cancel link mid-install.
    def request_close(self) -> bool:
        if self.state == "run":
            if self.engine.can_cancel():
                self._enter_ask()
            return False
        if self.state in ("ask", "stopping"):
            return False
        return True
