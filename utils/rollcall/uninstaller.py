"""The uninstaller window (frames D1 and D2): the installer's stage run
backwards. It starts full, a toon leaves as each step starts, and the colour
drains out of the window as it goes.

This is the one screen with no gold button: the destructive action is red
and the safe one is the ghost. Once it starts it cannot be cancelled.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication

from utils.rollcall import motion
from utils.rollcall import tokens as T
from utils.rollcall.controls import RcButton, RcCheckbox, RcLink
from utils.rollcall.engine import REMOVE_STEPS, Engine, Failure
from utils.rollcall.stage import (
    Actions, Body, Control, ErrorLine, Headline, Link, Micro, Percent,
)
from utils.rollcall.window import RollcallWindow


class UninstallerWindow(RollcallWindow):
    state_changed = Signal(str)

    def __init__(self, engine: Engine):
        self.engine = engine
        self.flavor = engine.flavor()
        super().__init__(T.LARGE, f"Uninstall {self.flavor.app_name}")
        self.state = ""
        self._follower = motion.RunFollower(len(REMOVE_STEPS))
        self._shown_step = -1
        self._wipe = False
        self._failure: Failure | None = None
        self._checkbox: RcCheckbox | None = None
        self._copy_link: RcLink | None = None
        self.stage.set_steps(REMOVE_STEPS, reverse=True)
        engine.step_progress.connect(self._on_progress)
        engine.finished.connect(self._on_finished)
        engine.failed.connect(self._on_failed)
        engine.app_closed.connect(self._on_app_closed)
        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self._refresh)
        if engine.app_running():
            self._enter_busy(animate=False)
        else:
            self._enter_idle(animate=False)

    def _set(self, state: str, items: list, animate: bool = True) -> None:
        self.state = state
        self._checkbox = None
        self._copy_link = None
        self.stage.copy.set_items(items, animate=animate)
        self.state_changed.emit(state)

    def _ghost(self, text: str, slot) -> RcButton:
        button = RcButton.ghost(text, self.variant)
        button.clicked.connect(slot)
        return button

    def _red(self, text: str, slot) -> RcButton:
        button = RcButton.red(text)
        button.clicked.connect(slot)
        return button

    def set_wipe(self, wipe: bool) -> None:
        """Tick or untick "Also remove my accounts, keysets and settings"."""
        self._wipe = bool(wipe)
        if self._checkbox is not None:
            self._checkbox.setChecked(self._wipe)

    def wipe(self) -> bool:
        return self._wipe

    # ── States ─────────────────────────────────────────────────────────────

    def _enter_idle(self, animate: bool = True) -> None:
        self.stage.set_crew(4, 4, animate=animate)
        checkbox = RcCheckbox("Also remove my accounts, keysets and settings",
                              self.engine.config_dir_display(), width=self.variant.copy_width)
        checkbox.setChecked(self._wipe)
        checkbox.toggled_by_user.connect(lambda on: setattr(self, "_wipe", bool(on)))
        self._set("idle", [
            Micro("Uninstall"),
            Headline(f"Remove {self.flavor.app_name}?", md=True),
            Body("The app and its shortcuts are removed. Your games aren’t touched."),
            Control(checkbox, gap=14),
            Actions([self._red("Uninstall", self._on_uninstall),
                     self._ghost("Keep it", self.close_now)]),
        ], animate)
        self._checkbox = checkbox

    def _enter_busy(self, animate: bool = True, problem: bool = False) -> None:
        self.stage.set_crew(4, 4, animate=animate)
        self._set("busy", [
            Micro("Couldn’t close it" if problem else "Before uninstalling", bad=problem),
            Headline(f"{self.flavor.short_name} is still running.", md=True),
            Body("Close it to continue. Your games aren’t touched."),
            Actions([self._red("Close & uninstall", self._on_close_and_uninstall),
                     self._ghost("Keep it", self.close_now)]),
        ], animate)

    def _enter_run(self) -> None:
        self._shown_step = 0
        self._follower.reset()
        self.stage.follow(self._follower)
        self.stage.set_crew(4, 3)
        self._set("run", [
            Micro("Removing · step 1 of 4"),
            Headline(REMOVE_STEPS[0], md=True),
            Percent("0%"),
        ])
        self._ticker.start()
        self.engine.uninstall(self._wipe)

    def _enter_done(self) -> None:
        self._ticker.stop()
        self._follower.fill()
        self.stage.follow(None)
        self.stage.set_fractions([1.0] * 4)
        self.stage.set_crew(4, 0)
        self.set_saturation(0.2)
        if self._wipe:
            body = Body("Accounts, keysets and settings were removed too.")
        else:
            body = Body.with_code("Your accounts and settings are still in ",
                                  self.engine.config_dir_display(), ".")
        self._set("done", [
            Micro("Removed"),
            Headline("The stage is clear.", md=True),
            body,
            Actions([self._ghost("Close", self.close_now)]),
        ])

    def _enter_fail(self, failure: Failure) -> None:
        self._ticker.stop()
        self._failure = failure
        step = max(0, min(3, failure.step))
        self.stage.follow(None)
        self.stage.set_fractions(list(self._follower.shown))
        self.stage.set_failed(step)
        items = [
            Micro(f"Stopped at step {step + 1} of 4", bad=True),
            Headline(failure.headline, md=True),
            Body(failure.body),
        ]
        if failure.detail:
            items.append(ErrorLine(failure.detail))
        items.append(Actions([self._ghost("Close", self.close_now)]))
        link = RcLink("Copy details")
        link.clicked.connect(self._on_copy_details)
        items.append(Link(link))
        self._set("fail", items)
        self._copy_link = link

    # ── Events ─────────────────────────────────────────────────────────────

    def _on_uninstall(self) -> None:
        if self.state != "idle":
            return
        if self.engine.app_running():
            self._enter_busy()
            return
        self._enter_run()

    def _on_close_and_uninstall(self) -> None:
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

    def _on_progress(self, step: int, fraction: float) -> None:
        if self.state == "run":
            self._follower.report(step, fraction)

    def _refresh(self) -> None:
        if self.state != "run":
            return
        step = self._follower.step
        if step != self._shown_step:
            self._shown_step = step
            self.stage.copy.set_micro(f"Removing · step {step + 1} of 4")
            self.stage.copy.set_headline(REMOVE_STEPS[step])
            # Toon 4 leaves when step 1 starts, then 3, 2, 1.
            self.stage.set_crew(4, 3 - step)
        overall = self._follower.overall()
        self.stage.copy.set_percent(f"{round(overall * 100)}%")
        self.set_saturation(1.0 - 0.8 * overall)

    def _on_finished(self) -> None:
        if self.state == "run":
            self._enter_done()

    def _on_failed(self, failure: Failure) -> None:
        if self.state == "run":
            self._enter_fail(failure)

    def _on_copy_details(self) -> None:
        if self._failure is None:
            return
        label = REMOVE_STEPS[max(0, min(3, self._failure.step))]
        QGuiApplication.clipboard().setText(self._failure.details_text(label))
        if self._copy_link is not None:
            self._copy_link.set_label("Copied")

    def request_close(self) -> bool:
        return self.state != "run"
