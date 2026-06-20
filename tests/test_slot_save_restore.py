"""Tests for _CompactLayout.capture_slot / restore_slot (Task 4.1a).

These are the foundation for the transparent-mode transactional reparent
(Task 4.1b): a card (grid-managed) or the emblem (manually positioned + raised)
is captured out of its exact place in the pinwheel and later reinserted into
THAT EXACT place. The helpers are dormant - nothing reparents into a surface
here - so framed mode is unchanged.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
        TTMT_CONFIG_DIR=$(mktemp -d) \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_slot_save_restore.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget


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


def _sp_equal(a, b) -> bool:
    return (
        a.horizontalPolicy() == b.horizontalPolicy()
        and a.verticalPolicy() == b.verticalPolicy()
    )


# ── Card (grid-managed) round-trip ───────────────────────────────────────────
@pytest.mark.parametrize("slot,expect_pos", [(0, (0, 0)), (3, (1, 1))])
def test_card_slot_round_trip(qapp, tab, slot, expect_pos):
    compact = tab._compact
    grid = compact._grid
    grid_host = compact._grid_host
    card = compact._cells[slot]["cell"]

    rec = compact.capture_slot(card)

    # Captured the right grid place + a copied size policy.
    assert rec.kind == "grid"
    assert (rec.row, rec.col) == expect_pos
    assert (rec.row_span, rec.col_span) == (1, 1)
    assert rec.parent is grid_host
    captured_visible = rec.visible
    assert _sp_equal(rec.size_policy, card.sizePolicy())

    # Reparent the card away: it leaves the grid.
    card.setParent(None)
    assert grid.indexOf(card) == -1, "card should be removed from the grid"

    # Mutating the LIVE widget's policy must not corrupt the snapshot (copy-by-
    # value). Stash the captured value, change the live widget, restore, then
    # confirm restore put the captured value back.
    from PySide6.QtWidgets import QSizePolicy
    card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    compact.restore_slot(rec)
    qapp.processEvents()

    # Back at the exact captured cell, under the grid host, policy + visibility
    # restored from the snapshot (not the post-capture mutation).
    idx = grid.indexOf(card)
    assert idx >= 0, "card should be back in the grid"
    assert grid.getItemPosition(idx)[:2] == expect_pos
    assert card.parentWidget() is grid_host
    # Intrinsic visibility round-trips (isVisible() is ancestor-dependent and is
    # False while the tab is unshown; the snapshot stores the intrinsic flag).
    assert (not card.isHidden()) == captured_visible
    assert _sp_equal(card.sizePolicy(), rec.size_policy)


# ── Emblem (manual, raised) round-trip ───────────────────────────────────────
def test_emblem_slot_round_trip(qapp, tab):
    compact = tab._compact
    grid_host = compact._grid_host
    emblem = compact._emblem

    # Position the cluster so the emblem has a meaningful geometry to restore.
    compact._relayout_all()
    qapp.processEvents()

    rec = compact.capture_slot(emblem)

    # Manual case: not in the grid, geometry + raised captured.
    assert rec.kind == "manual"
    assert rec.parent is grid_host
    assert rec.grid is None
    assert rec.raised is True, "emblem should be raised above the cards"
    captured_geo = rec.geometry
    captured_pos = rec.pos
    captured_visible = rec.visible

    # Reparent away, then restore.
    emblem.setParent(None)
    compact.restore_slot(rec)
    qapp.processEvents()

    assert emblem.parentWidget() is grid_host
    assert emblem.geometry() == captured_geo
    assert emblem.pos() == captured_pos
    assert (not emblem.isHidden()) == captured_visible  # intrinsic (see card test)
    # Raised back above the cards (top of the parent's widget stacking order).
    assert compact._is_topmost(emblem), "emblem should be raised above the cards"
    cards = {compact._cells[i]["cell"] for i in range(4)}
    widget_children = [c for c in grid_host.children() if isinstance(c, QWidget)]
    last_card_idx = max(widget_children.index(c) for c in cards)
    assert widget_children.index(emblem) > last_card_idx


# ── Symmetry: capture + restore WITHOUT reparenting away is a safe no-op ──────
def test_capture_restore_no_reparent_is_safe_for_card(qapp, tab):
    compact = tab._compact
    grid = compact._grid
    card = compact._cells[1]["cell"]

    before_count = grid.count()
    rec = compact.capture_slot(card)
    # Restore immediately, widget still in place: must not duplicate / error.
    compact.restore_slot(rec)
    qapp.processEvents()

    assert grid.count() == before_count, "restore must not add a duplicate grid item"
    idx = grid.indexOf(card)
    assert idx >= 0
    assert grid.getItemPosition(idx)[:2] == (0, 1)
    assert card.parentWidget() is compact._grid_host


def test_capture_restore_no_reparent_is_safe_for_emblem(qapp, tab):
    compact = tab._compact
    emblem = compact._emblem
    grid_host = compact._grid_host

    compact._relayout_all()
    qapp.processEvents()

    geo_before = emblem.geometry()
    rec = compact.capture_slot(emblem)
    compact.restore_slot(rec)
    qapp.processEvents()

    assert emblem.parentWidget() is grid_host
    assert emblem.geometry() == geo_before
    assert compact._is_topmost(emblem)


def test_restore_does_not_explicitly_hide_only_ancestor_hidden_card(qapp, tab):
    """The tab is unshown -> a card is ancestor-hidden (isVisible False) but was
    NEVER explicitly hidden (isHidden False). Capturing isVisible() + restoring
    via setVisible() would wrongly stick it explicitly hidden; capturing the
    intrinsic isHidden() flag avoids that (the transparent-mode case where the
    main window is minimized is the same ancestor-hidden scenario)."""
    compact = tab._compact
    card = compact._cells[0]["cell"]
    assert card.isHidden() is False                 # never explicitly hidden
    rec = compact.capture_slot(card)
    card.setParent(None)
    compact.restore_slot(rec)
    assert card.isHidden() is False, \
        "restore must not explicitly hide an only-ancestor-hidden card"


def test_restore_preserves_explicitly_hidden_card(qapp, tab):
    """The other direction: a genuinely (explicitly) hidden card must stay
    hidden after a capture/restore round-trip."""
    compact = tab._compact
    card = compact._cells[2]["cell"]
    card.setVisible(False)                           # explicitly hidden
    assert card.isHidden() is True
    rec = compact.capture_slot(card)
    card.setParent(None)
    compact.restore_slot(rec)
    assert card.isHidden() is True, \
        "an explicitly-hidden card must remain hidden after restore"
