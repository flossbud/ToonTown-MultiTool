"""CP20: screen-topology re-clamp. A dock/undock (or a relaunch that RACES the
display reconfiguration) can leave the model anchor off every live screen -
the restore clamp may validate against a transitional/empty screen list, and
nothing else ever re-validates. The controller now watches app-level
screenAdded/screenRemoved (+ per-screen geometryChanged) and, after a
debounced settle, re-clamps the anchor and re-places everything anchor-derived.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_cluster_topology_reclamp.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("TTMT_NO_RADIAL_ANIM", "1")
os.environ.setdefault("TTMT_NO_OVERLAY_SCALE_ANIM", "1")

from tests.test_cluster_controller import (   # reuse the recording-stub harness
    _make, _DictSettings, _PIVOT,
)
from utils.overlay.persistence import KEY_ANCHOR, KEY_MONITOR, KEY_SCALE


def _screen_center(ctrl):
    name, l, t, r, b = ctrl._screens()[0]
    return ((l + r) // 2, (t + b) // 2)


def test_reclamp_recenters_stranded_anchor_and_replaces_window(qapp):
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    surface = created[0]
    ctrl._anchor = (99999, 99999)              # stranded (off every screen)

    assert ctrl._revalidate_anchor_for_screens() is True

    cx, cy = _screen_center(ctrl)
    assert ctrl._anchor == (cx, cy)            # recentered on the first screen
    # The window followed: pivot sits on the re-clamped anchor.
    assert (surface.geom.x() + _PIVOT[0],
            surface.geom.y() + _PIVOT[1]) == (cx, cy)
    ctrl.leave()


def test_reclamp_noop_when_anchor_on_a_live_screen(qapp):
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    surface = created[0]
    cx, cy = _screen_center(ctrl)
    ctrl._anchor = (cx - 50, cy - 30)          # firmly on-screen
    geom_before = surface.geom

    assert ctrl._revalidate_anchor_for_screens() is False

    assert ctrl._anchor == (cx - 50, cy - 30)  # kept EXACT (no drift)
    assert surface.geom == geom_before         # nothing moved
    ctrl.leave()


def test_reclamp_defers_while_scaling(qapp):
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    ctrl._anchor = (99999, 99999)
    ctrl.set_scale_by_notches(1)               # scale gesture live
    assert ctrl._scaling_active is True

    assert ctrl._revalidate_anchor_for_screens() is False
    assert ctrl._anchor == (99999, 99999)      # untouched mid-gesture
    assert ctrl._topology_timer.isActive()     # retry re-armed

    ctrl._settle_input()
    assert ctrl._revalidate_anchor_for_screens() is True   # settles -> heals
    ctrl.leave()


def test_reclamp_retries_on_empty_screen_list(qapp, monkeypatch):
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    ctrl._anchor = (99999, 99999)
    monkeypatch.setattr(ctrl, "_screens", lambda: [])

    assert ctrl._revalidate_anchor_for_screens() is False
    assert ctrl._anchor == (99999, 99999)      # cannot validate -> untouched
    assert ctrl._topology_timer.isActive()     # retry armed for the real list
    ctrl.leave()


def test_reclamp_noop_when_inactive(qapp):
    ctrl, provider, window, created = _make()
    ctrl._anchor = (99999, 99999)
    assert ctrl._revalidate_anchor_for_screens() is False
    assert ctrl._anchor == (99999, 99999)


def test_enter_arms_settle_check_and_leave_disarms(qapp):
    """enter() always arms ONE deferred settle-check (covers topology events
    that fired before the watch was wired - the CP20 startup race); leave()
    stops the timer and drops the app-signal watch."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    assert ctrl._topology_timer is not None and ctrl._topology_timer.isActive()
    assert ctrl._topology_watching is True

    ctrl.leave()
    assert not ctrl._topology_timer.isActive()
    assert ctrl._topology_watching is False
    # A late event after leave() must be a harmless no-op.
    ctrl._on_topology_event()
    assert not ctrl._topology_timer.isActive()


def test_restore_keeps_anchor_verbatim_on_empty_screens(qapp, monkeypatch):
    """The restore clamp must NOT 'validate' against an empty (transitional)
    screen list: the saved anchor is adopted verbatim and the enter-time settle
    check owns the revalidation once screens exist."""
    s = _DictSettings({KEY_ANCHOR: [1855, 468], KEY_SCALE: 1.0,
                       KEY_MONITOR: "Ghost Display"})
    ctrl, provider, window, created = _make(settings=s)
    monkeypatch.setattr(ctrl, "_screens", lambda: [])

    assert ctrl._load_persisted_state() is True
    assert ctrl._anchor == (1855, 468)         # kept, flagged for revalidation


def test_restore_still_clamps_on_a_real_screen_list(qapp):
    """Regression guard: with a REAL screen list the restore clamp still
    recenters a stranded anchor exactly as before."""
    s = _DictSettings({KEY_ANCHOR: [999999, 999999], KEY_SCALE: 1.0,
                       KEY_MONITOR: "Ghost Display"})
    ctrl, provider, window, created = _make(settings=s)

    assert ctrl._load_persisted_state() is True
    cx, cy = _screen_center(ctrl)
    assert ctrl._anchor == (cx, cy)
