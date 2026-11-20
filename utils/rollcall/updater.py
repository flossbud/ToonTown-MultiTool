"""The update window (frames C1 and C2): the small window that stays on
screen while the app is closed for an update, so there is never a moment
with nothing there.

It has no buttons and cannot be closed while it works. It only asks for
anything when the update failed.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal

from utils.rollcall import motion
from utils.rollcall import tokens as T
from utils.rollcall.controls import RcButton
from utils.rollcall.engine import UPDATE_STEPS, Engine, Failure
from utils.rollcall.stage import Actions, Body, Headline, Micro
from utils.rollcall.window import RollcallWindow

STEP_HEADLINES = ("Closing up.", "Installing.", "Reopening.")
CLOSE_AFTER_MS = 1300        # the hop, then the window goes


class UpdateWindow(RollcallWindow):
    state_changed = Signal(str)

    def __init__(self, engine: Engine):
        self.engine = engine
        self.flavor = engine.flavor()
        super().__init__(T.SMALL, f"Updating {self.flavor.app_name}")
        self.state = ""
        self._follower = motion.RunFollower(len(UPDATE_STEPS))
        self._shown_step = -1
        self._present = 0
        engine.step_progress.connect(self._on_progress)
        engine.finished.connect(self._on_finished)
        engine.failed.connect(self._on_failed)
        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self._refresh)
        self._enter_run(animate=False)

    def _versions(self) -> str:
        old = self.engine.previous_version()
        return f"{old} → {self.flavor.version}" if old else self.flavor.version

    def _set(self, state: str, items: list, animate: bool = True) -> None:
        self.state = state
        self.stage.copy.set_items(items, animate=animate)
        self.state_changed.emit(state)

    def start(self) -> None:
        """Begin the update. Separate from construction so the window is on
        screen before the app is asked to go."""
        self.engine.update()

    def _enter_run(self, animate: bool = True) -> None:
        self._shown_step = 0
        self._present = 1
        self.stage.set_steps(UPDATE_STEPS)
        self._follower.reset()
        self.stage.follow(self._follower)
        self.stage.set_crew(4, 1, animate=animate)
        self._set("run", [
            Micro(self._versions()),
            Headline(STEP_HEADLINES[0]),
            Body(f"{self.flavor.short_name} reopens on its own."),
        ], animate)
        self._ticker.start()

    def _on_progress(self, step: int, fraction: float) -> None:
        if self.state == "run":
            self._follower.report(step, fraction)

    def _refresh(self) -> None:
        if self.state != "run":
            return
        step = self._follower.step
        if step != self._shown_step:
            self._shown_step = step
            self.stage.copy.set_headline(STEP_HEADLINES[step])
        # The toon count follows overall progress, not the step: the fourth
        # arrives in the last quarter.
        present = min(4, int(self._follower.overall() * 4) + 1)
        if present != self._present:
            self._present = present
            self.stage.set_crew(4, present)

    def _on_finished(self) -> None:
        if self.state != "run":
            return
        self._ticker.stop()
        self._follower.fill()
        self.stage.set_all_done()
        self.stage.set_crew(4, 4)
        self.state = "done"
        self.stage.copy.set_headline("Back in a second.")
        self.state_changed.emit("done")
        QTimer.singleShot(T.TOON_MOVE_MS if self._present < 4 else 0, self.stage.hop)
        QTimer.singleShot(CLOSE_AFTER_MS, self.close_now)

    def _on_failed(self, failure: Failure) -> None:
        if self.state != "run":
            return
        self._ticker.stop()
        step = max(0, min(2, failure.step))
        fractions = list(self._follower.shown)
        self.stage.follow(None)
        self.stage.set_fractions(
            [1.0 if i < step else (max(fractions[i], 0.08) if i == step else 0.0)
             for i in range(3)])
        self.stage.set_failed(step)
        old = self.engine.previous_version()
        if failure.previous_intact:
            # Everyone is on stage, because the old version is.
            self.stage.set_crew(4, 4)
            open_button = RcButton.gold(f"Open {self.flavor.short_name}", self.variant)
            open_button.clicked.connect(self._on_open)
            retry = RcButton.ghost("Retry", self.variant)
            retry.clicked.connect(self._on_retry)
            actions = [open_button, retry]
        else:
            self.stage.set_crew(4, step, bad=step)
            again = RcButton.gold("Try again", self.variant)
            again.clicked.connect(self._on_retry)
            close = RcButton.ghost("Close", self.variant)
            close.clicked.connect(self.close_now)
            actions = [again, close]
        self._set("fail", [
            Micro(f"Still on {old}" if old and failure.previous_intact else "Update stopped",
                  bad=True),
            Headline(failure.headline),
            Body(failure.body),
            Actions(actions),
        ])

    def _on_open(self) -> None:
        self.engine.open_app()
        self.close_now()

    def _on_retry(self) -> None:
        """Run the update again from the first step."""
        self._enter_run()
        self.engine.update()

    def request_close(self) -> bool:
        return self.state in ("fail", "done")
