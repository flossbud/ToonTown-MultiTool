"""Pin the post-refactor _FullLayout contract: cards arranged in a 2x2
grid, each card pinned to compact's 551 px width, shared per-toon
widgets reparented into full's card frames after a mode switch.

These tests must remain green as the foundation for any future
incremental divergence of full-mode cards from compact-mode cards."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QGridLayout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()
    return tab


def test_full_layout_has_four_card_slots(qapp, tmp_path, monkeypatch):
    """After switching to full mode, _FullLayout exposes four card slots
    with the same dict shape as _CompactLayout's _card_slots."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slots = tab._full._card_slots
    assert len(slots) == 4
    for slot in slots:
        assert "card" in slot
        assert "card_stripe" in slot
        assert "header_divider" in slot
        assert "ka_group" in slot


def test_full_layout_cards_are_in_2x2_grid(qapp, tmp_path, monkeypatch):
    """The 4 card frames live in a QGridLayout at positions
    (0,0), (0,1), (1,0), (1,1)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    grid = tab._full._card_grid
    assert isinstance(grid, QGridLayout)
    assert grid.rowCount() == 2
    assert grid.columnCount() == 2
    expected_positions = {(0, 0), (0, 1), (1, 0), (1, 1)}
    actual_positions = set()
    for i in range(4):
        card = tab._full._card_slots[i]["card"]
        for row in range(grid.rowCount()):
            for col in range(grid.columnCount()):
                item = grid.itemAtPosition(row, col)
                if item is not None and item.widget() is card:
                    actual_positions.add((row, col))
    assert actual_positions == expected_positions


def test_full_layout_card_width_matches_compact(qapp, tmp_path, monkeypatch):
    """Each card in full mode is pinned at compact's _LOCKED_CONTENT_WIDTH."""
    from tabs.multitoon._compact_layout import _LOCKED_CONTENT_WIDTH

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        card = tab._full._card_slots[i]["card"]
        assert card.minimumWidth() == _LOCKED_CONTENT_WIDTH
        assert card.maximumWidth() == _LOCKED_CONTENT_WIDTH


def test_full_layout_reparents_shared_widgets(qapp, tmp_path, monkeypatch):
    """After set_layout_mode('full'), shared per-toon widgets are
    parented into full's card frames (not compact's)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        chat = tab.chat_buttons[i]
        full_card = tab._full._card_slots[i]["card"]
        parent = chat.parentWidget()
        while parent is not None and parent is not full_card:
            parent = parent.parentWidget()
        assert parent is full_card, (
            f"chat_buttons[{i}] parent chain did not include the full "
            f"card frame; final parent: {chat.parentWidget()}"
        )


def test_full_layout_round_trip_to_compact(qapp, tmp_path, monkeypatch):
    """After full -> compact, shared widgets are reparented back into
    compact's card frames. Precondition: full mode must have reparented
    the widgets into its own frames first; otherwise the round-trip
    assertion is trivially satisfied."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)

    # Precondition: in full mode, widgets must live in full's frames.
    # This catches the case where full mode never reparents at all
    # (today's behavior) so the round-trip assertion below is meaningful.
    for i in range(4):
        chat = tab.chat_buttons[i]
        full_card = tab._full._card_slots[i]["card"]
        parent = chat.parentWidget()
        while parent is not None and parent is not full_card:
            parent = parent.parentWidget()
        assert parent is full_card, (
            f"precondition failure: chat_buttons[{i}] not parented into "
            f"full's card frame in full mode; round-trip below would be "
            f"vacuously true. Final parent: {chat.parentWidget()}"
        )

    tab.set_layout_mode("compact")
    for _ in range(5):
        qapp.processEvents()
    for i in range(4):
        chat = tab.chat_buttons[i]
        compact_card = tab._compact._card_slots[i]["card"]
        parent = chat.parentWidget()
        while parent is not None and parent is not compact_card:
            parent = parent.parentWidget()
        assert parent is compact_card, (
            f"chat_buttons[{i}] parent chain did not include the compact "
            f"card frame after switching back; final parent: {chat.parentWidget()}"
        )


def test_full_layout_body_color_drives_border(qapp, tmp_path, monkeypatch):
    """Body-derived border chrome works identically in full mode and
    compact mode: setting a body color on slot 0 produces the same
    darkened border in full's divider AND ka_group as it would in
    compact's (matches the body-derived chrome rule from
    test_card_body_tint_integration.py).

    Full's divider is pre-blended at 45 % over the body color rather
    than carrying the raw darkened border (full uses the blended
    solid color directly to avoid QGraphicsOpacityEffect, which
    renders invisible inside the QGraphicsView proxy in PySide6
    6.11). The ka_group still carries the un-blended darkened
    border. Both still encode the body-color signal."""
    from utils.color_math import darken_hsl
    from PySide6.QtGui import QColor
    from tabs.multitoon._full_layout import _blend_hex

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#e74a4a"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)

    expected = darken_hsl(QColor("#e74a4a"), 0.4).name()

    # ka_group still carries the raw darkened border color.
    ka_group = tab._full._card_slots[0].get("ka_group")
    assert ka_group is not None
    assert expected in ka_group.styleSheet()

    # Divider carries the 45 %-pre-blended version of that color over
    # the card body (which is the body color #e74a4a at full opacity
    # via CardBodyTint).
    expected_divider = _blend_hex(expected, "#e74a4a", 0.45)
    divider = tab._full._card_slots[0].get("header_divider")
    assert divider is not None
    assert expected_divider in divider.styleSheet()
