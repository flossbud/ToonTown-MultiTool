"""Pin the compact card header restack: top_row now nests a vertical
meta column (name + sub-line) between the portrait and the mode chip,
with the chip flush right. cc_subtitle_row is gone."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def _slot(tab, i):
    return tab._compact._card_slots[i]


def _layout_children(layout):
    """Return the widget/sub-layout children of `layout` in order."""
    out = []
    for k in range(layout.count()):
        item = layout.itemAt(k)
        w = item.widget()
        if w is not None:
            out.append(w)
        else:
            sub = item.layout()
            if sub is not None:
                out.append(sub)
    return out


def test_name_label_is_21_px(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    name_label, _ = tab.toon_labels[0]
    assert name_label.font().pixelSize() == 21


def test_stats_labels_are_14_px(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert tab.laff_labels[0].font().pixelSize() == 14
    assert tab.bean_labels[0].font().pixelSize() == 14


def test_name_stylesheet_survives_refresh(qapp, tmp_path, monkeypatch):
    """Regression: _refresh_toon_name_labels runs every time a toon name
    is discovered (7 callsites in _tab.py) and re-applies the name
    stylesheet. It must keep the 21 px size, otherwise the runtime font
    visually reverts even though the construction-time QFont test still
    passes."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Floss"
    tab._refresh_toon_name_labels()
    name_label, _ = tab.toon_labels[0]
    assert "font-size: 21px" in name_label.styleSheet(), (
        f"_refresh_toon_name_labels stripped the 21 px font-size. "
        f"Got stylesheet: {name_label.styleSheet()!r}"
    )


def test_top_row_order_portrait_meta_chip(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = _slot(tab, 0)
    children = _layout_children(slot["top_row"])
    assert len(children) == 3, f"top_row should have 3 children, got {len(children)}"
    assert children[0] is slot["portrait_placeholder"]
    assert isinstance(children[1], QVBoxLayout)
    assert children[1] is slot["meta_col"]
    assert children[2] is tab.game_badges[0]


def test_meta_col_holds_name_then_sub_row(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = _slot(tab, 0)
    name_label, _ = tab.toon_labels[0]
    children = _layout_children(slot["meta_col"])
    assert len(children) == 2
    assert children[0] is name_label
    assert isinstance(children[1], QHBoxLayout)
    assert children[1] is slot["sub_row"]


def test_sub_row_contains_laff_bean_cc_subtitle(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = _slot(tab, 0)
    children = _layout_children(slot["sub_row"])
    assert tab.laff_labels[0] in children
    assert tab.bean_labels[0] in children
    assert tab._compact_cc_subtitles[0] in children


def test_cc_subtitle_row_slot_removed(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = _slot(tab, 0)
    assert "cc_subtitle_row" not in slot


def test_laff_bean_height_capped_to_fit_placeholder(qapp, tmp_path, monkeypatch):
    """Regression: laff/bean QPushButtons must be capped so meta_col
    content (name 29 px + sub_row) stays within the 50 px portrait
    placeholder. Without the cap the system style chrome inflates the
    button sizeHint past 21 px, pushing the card height up by ~11 px
    when laff data populates.

    Note: only `maximumHeight` is checked - the stat_style QSS sets
    `min-height: 0` to let the button shrink below its style default,
    which overrides the Python-side `setMinimumHeight(20)` from
    `setFixedHeight`. The cap on the max side is what prevents card
    growth; the min side stays at 0 by design."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert tab.laff_labels[0].maximumHeight() == 20
    assert tab.bean_labels[0].maximumHeight() == 20
