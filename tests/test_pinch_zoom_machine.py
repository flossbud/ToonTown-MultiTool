"""Unit suite for the pure pinch-zoom state machine.

Pure module - no Qt, no timers, no wall clock. Every rule here maps to
section 2.1 of docs/superpowers/specs/2026-07-05-trackpad-pinch-zoom-design.md:
decisions are return values, the machine never executes effects, and every
malformed sequence (update/end/cancel in IDLE, begin while ACTIVE) has a
defined, pinned outcome.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_pinch_zoom_machine.py -v
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys

import pytest

from utils.overlay.pinch_zoom import (
    PINCH_WATCHDOG_MS,
    Commit,
    PinchState,
    PinchZoomStateMachine,
)
from utils.overlay.scale import SCALE_MAX, SCALE_MIN, SNAP_TARGET, SNAP_WINDOW


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Purity ───────────────────────────────────────────────────────────────────

class TestPurity:
    def test_import_pulls_no_qt(self):
        """The machine must be importable on any platform with zero Qt.

        Run in a subprocess: this pytest process already has PySide6 loaded
        via conftest, so only a fresh interpreter can prove the import is
        Qt-free.
        """
        code = (
            "import sys; import utils.overlay.pinch_zoom; "
            "leaked = [m for m in sys.modules if 'PySide6' in m]; "
            "assert not leaked, f'Qt leaked into a pure module: {leaked}'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

    def test_commit_is_frozen(self):
        c = Commit(scale=1.2, snapped=False)
        assert c.scale == 1.2
        assert c.snapped is False
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.scale = 2.0

    def test_watchdog_constant(self):
        """The machine only PUBLISHES the deadline; the integration layer
        owns the timer and calls expire()."""
        assert PINCH_WATCHDOG_MS == 1500


# ── begin() ──────────────────────────────────────────────────────────────────

class TestBegin:
    def test_begin_from_idle_enters_active_returns_none(self):
        m = PinchZoomStateMachine()
        assert m.active is False
        assert m.begin(1.2) is None
        assert m.active is True
        assert m.state is PinchState.ACTIVE
        assert m.live_scale == 1.2

    def test_begin_coerces_base_to_float(self):
        m = PinchZoomStateMachine()
        m.begin(1)  # int base
        assert isinstance(m.live_scale, float)
        assert m.live_scale == 1.0
        # update math must run on the coerced float
        assert m.update(1.5) == pytest.approx(1.5)

    def test_begin_while_active_commits_current_live_with_cancel_semantics(self):
        """Lost end: the new physical gesture must not discard the first
        gesture's result. The commit carries the CURRENT live scale, never
        snapped (cancel semantics)."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.02)  # inside the snap window: end() would snap, begin() must not
        c = m.begin(1.02)
        assert isinstance(c, Commit)
        assert c.scale == pytest.approx(1.02)
        assert c.snapped is False

    def test_begin_while_active_rebases_on_committed_live_not_argument(self):
        """Re-begin uses the committed live scale as the fresh base: the new
        gesture's factor stream restarts near 1.0, so a stale (or caller
        supplied) base would snap the scale back."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.4)
        m.begin(999.0)  # argument must be ignored on the ACTIVE path
        assert m.active is True
        assert m.live_scale == pytest.approx(1.4)
        # factor 1.0 = "gesture just restarted": scale must hold at 1.4
        assert m.update(1.0) == pytest.approx(1.4)

    def test_begin_while_active_full_scenario(self):
        """First gesture zooms 1.0 -> 1.4, its end is lost, a second gesture
        begins: the second gesture's early factors (near 1.0) scale FROM 1.4.
        Stale-base math would yield 1.02 here and visibly snap the cluster
        back, discarding the first gesture."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.1)
        m.update(1.4)  # first gesture ends up at 1.4; end() never arrives
        c = m.begin(1.4)
        assert c == Commit(scale=pytest.approx(1.4), snapped=False)
        live = m.update(1.02)
        assert live == pytest.approx(1.428)  # 1.4 * 1.02, NOT 1.02
        done = m.end()
        assert done.scale == pytest.approx(1.428)
        assert done.snapped is False


# ── update() ─────────────────────────────────────────────────────────────────

class TestUpdate:
    def test_update_in_idle_is_defined_noop(self):
        m = PinchZoomStateMachine()
        assert m.update(1.3) is None
        assert m.active is False
        assert m.live_scale is None

    def test_update_scales_base_by_absolute_factor(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        assert m.update(1.25) == pytest.approx(1.25)
        assert m.live_scale == pytest.approx(1.25)

    def test_update_factor_is_absolute_since_begin_not_incremental(self):
        """Direction change within one gesture: each factor replaces the
        last (absolute-since-begin), it never compounds on prior updates."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        assert m.update(1.3) == pytest.approx(1.3)   # zoom in...
        assert m.update(0.8) == pytest.approx(0.8)   # ...then pinch back through 1.0
        assert m.update(1.05) == pytest.approx(1.05)

    def test_update_clamps_at_scale_max(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        assert m.update(50.0) == pytest.approx(SCALE_MAX)
        assert m.live_scale == pytest.approx(SCALE_MAX)

    def test_update_clamps_at_scale_min(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        assert m.update(0.01) == pytest.approx(SCALE_MIN)
        assert m.live_scale == pytest.approx(SCALE_MIN)

    def test_update_nonpositive_factor_ignored(self):
        """Defensive: a zero/negative factor is malformed input; ignore it
        and leave the live scale untouched."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.2)
        assert m.update(0.0) is None
        assert m.update(-0.5) is None
        assert m.live_scale == pytest.approx(1.2)
        assert m.active is True


# ── end() ────────────────────────────────────────────────────────────────────

class TestEnd:
    def test_end_in_idle_is_defined_noop(self):
        m = PinchZoomStateMachine()
        assert m.end() is None

    def test_end_returns_to_idle_and_clears_live(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.5)
        m.end()
        assert m.active is False
        assert m.state is PinchState.IDLE
        assert m.live_scale is None

    def test_end_outside_snap_window_commits_live_unsnapped(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.5)
        c = m.end()
        assert c == Commit(scale=pytest.approx(1.5), snapped=False)

    def test_end_inside_snap_window_snaps_to_target(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.03)  # |1.03 - 1.0| < SNAP_WINDOW (0.04)
        c = m.end()
        assert c.scale == SNAP_TARGET
        assert c.snapped is True

    def test_end_snap_window_below_target_too(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(0.97)
        c = m.end()
        assert c.scale == SNAP_TARGET
        assert c.snapped is True

    def test_end_just_outside_snap_window_does_not_snap(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        outside = SNAP_TARGET + SNAP_WINDOW + 0.001
        m.update(outside)
        c = m.end()
        assert c.scale == pytest.approx(outside)
        assert c.snapped is False

    def test_end_with_no_updates_commits_base(self):
        m = PinchZoomStateMachine()
        m.begin(1.5)
        c = m.end()
        assert c == Commit(scale=pytest.approx(1.5), snapped=False)

    def test_full_happy_path(self):
        """begin / update*N / end - the normal gesture life cycle."""
        m = PinchZoomStateMachine()
        assert m.begin(1.0) is None
        for factor in (1.01, 1.05, 1.12, 1.20, 1.26):
            assert m.update(factor) == pytest.approx(factor)
        c = m.end()
        assert c == Commit(scale=pytest.approx(1.26), snapped=False)
        assert m.active is False
        # the machine is reusable for the next gesture
        assert m.begin(1.26) is None
        assert m.update(1.0) == pytest.approx(1.26)


# ── cancel() / expire() ──────────────────────────────────────────────────────

class TestCancelAndExpire:
    def test_cancel_in_idle_is_defined_noop(self):
        m = PinchZoomStateMachine()
        assert m.cancel() is None

    def test_cancel_commits_live_without_snap(self):
        """Inside the snap window, end() would snap; cancel() must NOT."""
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.02)
        c = m.cancel()
        assert c == Commit(scale=pytest.approx(1.02), snapped=False)
        assert m.active is False
        assert m.live_scale is None

    def test_expire_in_idle_is_defined_noop(self):
        m = PinchZoomStateMachine()
        assert m.expire() is None

    def test_expire_behaves_exactly_like_cancel(self):
        m = PinchZoomStateMachine()
        m.begin(1.0)
        m.update(1.03)  # inside the snap window
        c = m.expire()
        assert c == Commit(scale=pytest.approx(1.03), snapped=False)
        assert m.active is False
        assert m.live_scale is None

    def test_expire_shares_cancel_implementation(self):
        """expire() IS cancel(): one termination behavior, no drift."""
        assert PinchZoomStateMachine.expire is PinchZoomStateMachine.cancel


# ── active / live_scale observers ────────────────────────────────────────────

class TestObservers:
    def test_active_tracks_state_across_lifecycle(self):
        m = PinchZoomStateMachine()
        assert m.active is False
        m.begin(1.0)
        assert m.active is True
        m.end()
        assert m.active is False
        m.begin(1.0)
        m.cancel()
        assert m.active is False

    def test_live_scale_none_when_idle_current_when_active(self):
        m = PinchZoomStateMachine()
        assert m.live_scale is None
        m.begin(1.1)
        assert m.live_scale == pytest.approx(1.1)
        m.update(1.2)
        assert m.live_scale == pytest.approx(1.1 * 1.2)
        m.cancel()
        assert m.live_scale is None
