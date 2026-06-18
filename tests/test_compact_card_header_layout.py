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


def test_name_label_is_23_px(qapp, tmp_path, monkeypatch):
    # Pinwheel compact name size: _CompactLayout._populate_cell sets
    # setFont(pixelSize 23, Bold). (Pre-pinwheel this was 21 px.)
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    name_label, _ = tab.toon_labels[0]
    assert name_label.font().pixelSize() == 23


def test_stats_labels_are_14_px(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert tab.laff_labels[0].font().pixelSize() == 14
    assert tab.bean_labels[0].font().pixelSize() == 14


def test_name_size_survives_refresh(qapp, tmp_path, monkeypatch):
    """Regression (pinwheel judder): _refresh_toon_name_labels runs on every
    name discovery / 5 s auto-refresh. It must NOT impose its own font size —
    the name font is owned by the layout (compact setFont(23)). Previously this
    method re-applied a stale `font-size: 21px` stylesheet that fought the
    layout's 23 px, so the name flipped 23<->21 each refresh (visible judder)
    and the sizeHint delta shifted the bottom-row portraits. After a refresh the
    rendered size must stay the layout-owned 23 px (and the text must update)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    name_label, _ = tab.toon_labels[0]
    before = name_label.font().pixelSize()
    tab.toon_names[0] = "Floss"
    tab._refresh_toon_name_labels()
    assert name_label.text() == "Floss", "refresh must still update the label text"
    assert name_label.font().pixelSize() == before == 23, (
        f"refresh changed the name font size from {before} to "
        f"{name_label.font().pixelSize()}; it must stay layout-owned 23 px"
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
