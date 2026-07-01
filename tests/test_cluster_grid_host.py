"""Tests for _CompactLayout.capture_cluster_host / restore_cluster_host (Task 2).

The single-window overlay borrows the ENTIRE `_grid_host` subtree (glow + the
2x2 card grid + the emblem) as ONE unit, replacing the old per-card/per-emblem
borrow. capture_cluster_host() detaches the whole host (parentless) and returns
a restore TOKEN; restore_cluster_host(token) puts it back EXACTLY (outer layout,
index, stretch, visibility, size policy/min/max). The framed path never calls
these, so it is unaffected.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_cluster_grid_host.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QSizePolicy


class _FakeWindowManager(QObject):
    """Minimal stand-in for WindowManager (same shape as the other tab tests)."""

    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def get_active_window(self):
        return None

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """A fully-built MultitoonTab (real card/emblem build path) under config +
    keyring isolation. Relies on conftest's autouse input_service shutdown."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    # The launch tab probes for CC installs during build; stub it out so the
    # tab build path is hermetic.
    import tabs.launch_tab
    monkeypatch.setattr(tabs.launch_tab, "discover_cc_installs", lambda *a, **k: [])

    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


# ── 1. Whole-cluster round-trip ──────────────────────────────────────────────
def test_cluster_host_round_trip(qapp, tab):
    compact = tab._compact
    outer = compact._outer
    host = compact._grid_host

    parent_before = outer.parentWidget()          # the _CompactLayout itself
    index_before = outer.indexOf(host)
    stretch_before = outer.stretch(index_before)
    assert index_before >= 0
    assert parent_before is not None

    token = compact.capture_cluster_host()

    # Detached: parentless, gone from the outer layout.
    assert host.parent() is None, "capture must detach the host (parentless)"
    assert outer.indexOf(host) == -1, "host should be gone from the outer layout"

    compact.restore_cluster_host(token)
    qapp.processEvents()

    # Re-parented back to the outer layout's parent, at the original index +
    # stretch, and it is the SAME object (never recreated/deleted).
    assert host.parentWidget() is parent_before
    idx = outer.indexOf(host)
    assert idx == index_before
    assert outer.stretch(idx) == stretch_before
    assert compact._grid_host is host


# ── 2. Visibility restored ───────────────────────────────────────────────────
def test_cluster_host_visibility_restored(qapp, tab):
    compact = tab._compact
    host = compact._grid_host

    # Explicitly hide the host, then capture its (hidden) state.
    host.setVisible(False)
    assert host.isHidden() is True
    token = compact.capture_cluster_host()

    # Mutate live visibility after capture - restore must use the snapshot.
    host.setVisible(True)
    compact.restore_cluster_host(token)
    qapp.processEvents()

    assert host.isHidden() is True, "restore must put back the recorded hidden state"


def test_cluster_host_visible_state_restored(qapp, tab):
    """The other direction: a not-explicitly-hidden host stays not-hidden."""
    compact = tab._compact
    host = compact._grid_host
    assert host.isHidden() is False
    token = compact.capture_cluster_host()
    compact.restore_cluster_host(token)
    assert host.isHidden() is False


# ── 3. Size constraints restored (policy + min + max, copy-by-value) ──────────
def test_cluster_host_size_constraints_restored(qapp, tab):
    compact = tab._compact
    host = compact._grid_host

    host.setMinimumSize(123, 45)
    host.setMaximumSize(678, 910)
    host.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
    min_before = QSize(host.minimumSize())
    max_before = QSize(host.maximumSize())
    sp_h_before = host.sizePolicy().horizontalPolicy()
    sp_v_before = host.sizePolicy().verticalPolicy()

    token = compact.capture_cluster_host()

    # Mutate the LIVE widget post-capture; the snapshot is copy-by-value.
    host.setMinimumSize(1, 1)
    host.setMaximumSize(2, 2)
    host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    compact.restore_cluster_host(token)
    qapp.processEvents()

    assert host.minimumSize() == min_before
    assert host.maximumSize() == max_before
    assert host.sizePolicy().horizontalPolicy() == sp_h_before
    assert host.sizePolicy().verticalPolicy() == sp_v_before


# ── 4. Idempotent: a second restore is a safe no-op (parented once) ──────────
def test_cluster_host_restore_idempotent(qapp, tab):
    compact = tab._compact
    outer = compact._outer
    host = compact._grid_host

    token = compact.capture_cluster_host()
    compact.restore_cluster_host(token)
    compact.restore_cluster_host(token)   # second call must not raise/duplicate
    qapp.processEvents()

    # The host appears exactly once in the outer layout.
    occurrences = [
        i for i in range(outer.count())
        if outer.itemAt(i) is not None and outer.itemAt(i).widget() is host
    ]
    assert occurrences == [outer.indexOf(host)]
    assert len(occurrences) == 1
    assert host.parentWidget() is outer.parentWidget()


# ── 5. Fail-closed: None / malformed token must not raise ─────────────────────
def test_cluster_host_restore_fail_closed(qapp, tab):
    compact = tab._compact
    # None, empty dict, and arbitrary garbage must all be safe no-ops.
    compact.restore_cluster_host(None)
    compact.restore_cluster_host({})
    compact.restore_cluster_host("not a token")
    compact.restore_cluster_host(12345)
    compact.restore_cluster_host(object())


# ── 6. Re-entrant capture must not record a degraded token ────────────────────
def test_cluster_host_capture_idempotent_reentrant(qapp, tab):
    compact = tab._compact
    host = compact._grid_host
    outer = compact._outer
    idx0 = outer.indexOf(host)
    stretch0 = outer.stretch(idx0)
    assert idx0 >= 0

    t1 = compact.capture_cluster_host()
    # A second capture while the first is still outstanding (host already
    # detached) must return the SAME valid token, NOT a degraded index=-1/stretch=0
    # one (which would restore the framed layout to the wrong slot).
    t2 = compact.capture_cluster_host()
    assert t2 is t1
    assert t1.index == idx0 and t1.stretch == stretch0

    compact.restore_cluster_host(t1)                       # back to the ORIGINAL slot
    assert outer.indexOf(host) == idx0
    assert outer.stretch(outer.indexOf(host)) == stretch0

    # After a successful restore the marker is cleared, so a fresh capture
    # derives a NEW valid token (not the stale one).
    t3 = compact.capture_cluster_host()
    assert t3 is not t1 and t3.index == idx0 and t3.stretch == stretch0
    compact.restore_cluster_host(t3)                       # leave framed mode intact
