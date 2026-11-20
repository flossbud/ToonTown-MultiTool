"""Time for the Roll Call stage: one clock, tweens that read it, and the
progress follower that turns an engine's coarse reports into smooth stripes.

Tweens are plain values sampled at paint time, not QPropertyAnimations: a
render harness or a test moves the clock by hand (``set_now``) and gets the
exact frame it asked for.

With reduced motion on, transforms are dropped and opacity changes stay (the
design's rule); callers ask ``is_reduced()`` where they move things.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QElapsedTimer

from utils.rollcall.tokens import EASE_SETTLE

_timer = QElapsedTimer()
_timer.start()
_now_override: float | None = None
_reduced = False


def now() -> float:
    """Milliseconds on the stage clock."""
    if _now_override is not None:
        return _now_override
    return float(_timer.elapsed())


def set_now(ms: float | None) -> None:
    """Freeze the clock at ``ms`` (renders, tests); None lets it run again."""
    global _now_override
    _now_override = None if ms is None else float(ms)


def advance(ms: float) -> None:
    """Move a frozen clock forward."""
    set_now(now() + ms)


def set_reduced(reduced: bool) -> None:
    global _reduced
    _reduced = bool(reduced)


def is_reduced() -> bool:
    return _reduced


class Tween:
    """A number on its way somewhere."""

    __slots__ = ("_from", "_to", "_t0", "_ms", "_ease")

    def __init__(self, value: float = 0.0):
        self._from = self._to = float(value)
        self._t0 = 0.0
        self._ms = 0.0
        self._ease: QEasingCurve = EASE_SETTLE

    @property
    def target(self) -> float:
        return self._to

    def snap(self, value: float) -> None:
        self._from = self._to = float(value)
        self._ms = 0.0

    def to(self, value: float, ms: float, ease: QEasingCurve = EASE_SETTLE,
           delay: float = 0.0) -> None:
        """Head for ``value`` from wherever the tween is now."""
        self._from = self.value()
        self._to = float(value)
        self._t0 = now() + delay
        self._ms = float(ms)
        self._ease = ease
        if ms <= 0 and delay <= 0:
            self._from = self._to

    def restart(self, start: float, value: float, ms: float,
                ease: QEasingCurve = EASE_SETTLE, delay: float = 0.0) -> None:
        self._from = float(start)
        self._to = float(value)
        self._t0 = now() + delay
        self._ms = float(ms)
        self._ease = ease

    def progress(self) -> float:
        """0..1 along the clock, before easing."""
        if self._ms <= 0:
            return 1.0 if now() >= self._t0 else 0.0
        return max(0.0, min(1.0, (now() - self._t0) / self._ms))

    def value(self) -> float:
        t = self.progress()
        if t >= 1.0:
            return self._to
        if t <= 0.0:
            return self._from
        return self._from + (self._to - self._from) * self._ease.valueForProgress(t)

    def active(self) -> bool:
        return self._from != self._to and now() < self._t0 + self._ms


class RunFollower:
    """What the floor shows of a run: one fraction per step.

    The engine reports (step, fraction) when it can. This eases the shown
    fractions toward the reported ones, completes earlier steps, and lets a
    step that reports INDETERMINATE creep toward 90 % so the stripe is never
    dead. ``frame`` is called once per painted frame.
    """

    CATCH_UP_MS = 220.0       # time constant of the ease toward a reported value
    CREEP_MS = 2600.0         # time constant of an unmeasured step's creep
    CREEP_LIMIT = 0.9

    def __init__(self, steps: int):
        self.steps = steps
        self.shown = [0.0] * steps
        self._target = [0.0] * steps
        self._creeping = [False] * steps
        self.step = 0
        self.held = False
        self._last = now()

    def reset(self, keep_before: int = 0) -> None:
        """Start over. Steps before ``keep_before`` stay complete (a retry
        restarts at the step that failed)."""
        for i in range(self.steps):
            done = 1.0 if i < keep_before else 0.0
            self.shown[i] = self._target[i] = done
            self._creeping[i] = False
        self.step = min(keep_before, self.steps - 1)
        self.held = False
        self._last = now()

    def fill(self) -> None:
        for i in range(self.steps):
            self.shown[i] = self._target[i] = 1.0
            self._creeping[i] = False
        self.step = self.steps - 1

    def report(self, step: int, fraction: float) -> None:
        step = max(0, min(self.steps - 1, int(step)))
        if step < self.step:
            return                      # a run never goes back
        for i in range(step):
            self._target[i] = 1.0
            self._creeping[i] = False
        self.step = step
        if fraction < 0:
            self._creeping[step] = True
        else:
            self._creeping[step] = False
            self._target[step] = max(self._target[step], min(1.0, float(fraction)))

    def finish(self) -> None:
        for i in range(self.steps):
            self._target[i] = 1.0
            self._creeping[i] = False
        self.step = self.steps - 1

    def frame(self) -> bool:
        """Advance to the clock. True while anything is still moving."""
        t = now()
        dt = max(0.0, min(250.0, t - self._last))
        self._last = t
        if self.held:
            return False
        moving = False
        for i in range(self.steps):
            if self._creeping[i]:
                goal = max(self._target[i], self.CREEP_LIMIT)
                self._target[i] += (goal - self._target[i]) * min(1.0, dt / self.CREEP_MS)
                moving = True
            gap = self._target[i] - self.shown[i]
            if abs(gap) < 0.0005:
                self.shown[i] = self._target[i]
            else:
                self.shown[i] += gap * min(1.0, dt / self.CATCH_UP_MS)
                moving = True
        return moving

    def overall(self) -> float:
        return sum(self.shown) / self.steps if self.steps else 0.0

    def settled(self) -> bool:
        return all(abs(s - t) < 0.0005 for s, t in zip(self.shown, self._target))
