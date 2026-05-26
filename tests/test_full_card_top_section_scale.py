"""Pin the full-mode top-section scaling contract.

Full cards are 190 px tall (1.62x of compact natural 117). Inside that
card the top section (portrait, name, stats) is bumped up: placeholder
+ badge 50/64 -> 120, status dot 13 -> 24, name font 21 -> 23 px,
stats font 14 -> 15 px, stats icon 16 -> 17 px. Bottom section
(toon_button, chat, KA, selector, ka_bar) is unchanged from compact.
Compact mode is unchanged end-to-end.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QApplication


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


def test_full_mode_card_height_is_190(qapp, tmp_path, monkeypatch):
    """Every card in full mode has fixed height = _FULL_CARD_HEIGHT (190)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        card = tab._full._card_slots[i]["card"]
        assert card.minimumHeight() == 190, (
            f"slot {i}: expected 190, got minimumHeight={card.minimumHeight()}"
        )
        assert card.maximumHeight() == 190


def test_full_mode_portrait_placeholder_is_120(qapp, tmp_path, monkeypatch):
    """Layout slot for the portrait reserves 120x120 (was 50x50 in compact)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        placeholder = tab._full._card_slots[i].get("portrait_placeholder")
        assert placeholder is not None
        assert placeholder.minimumWidth() == 120
        assert placeholder.minimumHeight() == 120
        assert placeholder.maximumWidth() == 120
        assert placeholder.maximumHeight() == 120


def test_full_mode_badge_is_120(qapp, tmp_path, monkeypatch):
    """slot_badges (the actual portrait widget) is 120x120 in full mode."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        badge = tab.slot_badges[i]
        assert badge.minimumSize() == QSize(120, 120)
        assert badge.maximumSize() == QSize(120, 120)


def test_full_mode_status_dot_is_24(qapp, tmp_path, monkeypatch):
    """PulsingDot core size scales 13 -> 24 in full mode."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        _, status_dot = tab.toon_labels[i]
        assert status_dot._dot_size == 24, (
            f"slot {i}: expected 24, got {status_dot._dot_size}"
        )


def test_full_mode_name_font_is_23_px(qapp, tmp_path, monkeypatch):
    """Name label font scales 21 -> 23 px in full mode."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        name_label, _ = tab.toon_labels[i]
        assert name_label.font().pixelSize() == 23, (
            f"slot {i}: expected 23 px, got {name_label.font().pixelSize()}"
        )


def test_full_mode_stats_font_is_15_px(qapp, tmp_path, monkeypatch):
    """Laff and bean labels' font scales 14 -> 15 px in full mode."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        assert tab.laff_labels[i].font().pixelSize() == 15, (
            f"slot {i} laff: expected 15 px, got {tab.laff_labels[i].font().pixelSize()}"
        )
        assert tab.bean_labels[i].font().pixelSize() == 15, (
            f"slot {i} bean: expected 15 px, got {tab.bean_labels[i].font().pixelSize()}"
        )


def test_full_mode_stats_icon_is_17_px(qapp, tmp_path, monkeypatch):
    """Laff and bean label icon size scales 16 -> 17 px in full mode."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        assert tab.laff_labels[i].iconSize() == QSize(17, 17), (
            f"slot {i} laff: expected QSize(17, 17), got {tab.laff_labels[i].iconSize()}"
        )
        assert tab.bean_labels[i].iconSize() == QSize(17, 17), (
            f"slot {i} bean: expected QSize(17, 17), got {tab.bean_labels[i].iconSize()}"
        )


def test_full_mode_card_does_not_clip_content(qapp, tmp_path, monkeypatch):
    """Layout sizeHint must fit within the 190 px card height. Regression
    guard against future content additions clipping the bottom row."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for i in range(4):
        card = tab._full._card_slots[i]["card"]
        card.layout().activate()
        hint = card.layout().sizeHint().height()
        assert hint <= 190, (
            f"slot {i}: layout sizeHint {hint} px exceeds card height 190 — "
            f"content will clip. Reduce some top-section element or grow "
            f"_FULL_CARD_HEIGHT."
        )


def test_compact_mode_unchanged_after_full_round_trip(qapp, tmp_path, monkeypatch):
    """Going full -> compact restores all compact sizes on the shared
    widgets. Pins the divergence to full mode only."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.set_layout_mode("compact")
    for _ in range(5):
        qapp.processEvents()
    for i in range(4):
        # Badge back to 64x64 (compact size).
        badge = tab.slot_badges[i]
        assert badge.minimumSize() == QSize(64, 64), (
            f"slot {i}: badge not restored to 64x64 after full->compact"
        )
        # Name font back to 21 px.
        name_label, status_dot = tab.toon_labels[i]
        assert name_label.font().pixelSize() == 21
        # Stats font back to 14 px.
        assert tab.laff_labels[i].font().pixelSize() == 14
        # Stats icon back to 16 px.
        assert tab.laff_labels[i].iconSize() == QSize(16, 16)
        assert tab.bean_labels[i].font().pixelSize() == 14
        assert tab.bean_labels[i].iconSize() == QSize(16, 16)
        # Status dot back to 13.
        assert status_dot._dot_size == 13
