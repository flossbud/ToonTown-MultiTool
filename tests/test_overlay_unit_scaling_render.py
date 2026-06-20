"""Lock-unit render invariant (Task 6 of the overlay unit-scaling plan).

A card is laid out ONCE at its framed 1.0 size and shown through a per-card
ScaledCardView whose transform applies the group scale. So every control keeps
the SAME position RELATIVE to its card at any scale - nothing floats. If this
test ever fails, a per-scale re-layout was reintroduced (the float bug).

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
        TTMT_CONFIG_DIR=$(mktemp -d) \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_overlay_unit_scaling_render.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal


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
    """A fully-built MultitoonTab under config + keyring isolation."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
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


def _rel_center(card, child):
    c = child.mapTo(card, child.rect().center())
    return (c.x() / max(card.width(), 1), c.y() / max(card.height(), 1))


def test_controls_stay_locked_across_scales(qapp, tab):
    """Every control keeps the same RELATIVE position at any scale (no float)."""
    from utils.overlay.scaled_card_view import ScaledCardView
    from PySide6.QtWidgets import QWidget

    bw, bh = tab._compact.overlay_base_card_size()
    card = tab._compact.slot_widget(0)
    card.setFixedSize(bw, bh)
    qapp.processEvents()

    # Pick controls that are genuinely descendants of slot 0's card (mapTo needs
    # an ancestor-chain), across the card so a re-layout anywhere would be caught.
    candidates = [
        tab.toon_buttons[0],
        tab.set_selectors[0],
        tab.keep_alive_buttons[0],
    ]
    controls = [c for c in candidates if isinstance(c, QWidget) and card.isAncestorOf(c)]
    assert controls, "no control is a descendant of slot 0's card"

    v = ScaledCardView()
    v.set_card(card)
    try:
        # Reference is taken AFTER embedding at 1.0 (embedding detaches the card
        # from the grid, which re-lays it out once at its fixed bw x bh). The
        # invariant under test is that the per-card VIEW TRANSFORM does not move
        # any control RELATIVE to the card at any other scale.
        v.set_scale(1.0)
        qapp.processEvents()
        refs = [_rel_center(card, c) for c in controls]
        for s in (0.5, 1.75):
            v.set_scale(s)
            qapp.processEvents()
            for c, ref in zip(controls, refs):
                assert _rel_center(card, c) == ref, f"control floated at scale {s}"
    finally:
        v.release_card()
