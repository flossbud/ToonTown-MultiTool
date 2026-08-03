"""FeaturePill unit behavior (label, click signal, dim/scale API).
Tab-level state-machine tests (label transitions driven through real
settings writes) live in the same file and are added with the tab wiring."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_pill_defaults_and_label(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    assert pill.label() == "Enable features"


def test_pill_click_emits(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.resize(158, 38)
    hits = []
    pill.clicked.connect(lambda: hits.append(True))
    QTest.mouseClick(pill, Qt.LeftButton, pos=QPoint(79, 19))
    assert hits == [True]


def test_pill_dim_and_scale_apis(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.set_dim_progress(0.5)
    pill.set_dim_progress(2.0)   # clamps, no raise
    pill.set_paint_scale(1.5)
    pill.set_paint_scale(1.5)    # idempotent, no raise


def test_pill_paint_smoke_across_envelope(qapp):
    """Exercise the paint path at the real control-column size across the
    CardMetrics scale envelope, fully dimmed, and with a long label. The
    widget is almost entirely paint math; grab() renders offscreen and any
    QPainter misuse raises or warns."""
    from tabs.multitoon._feature_pill import FeaturePill
    from utils.overlay.card_metrics import CardMetrics
    pill = FeaturePill()
    for scale in (0.5, 1.0, 1.75):
        m = CardMetrics(scale)
        pill.setFixedHeight(m.keyset_h)
        pill.resize(m.ctrl_w, m.keyset_h)
        pill.set_paint_scale(m.scale)
        for dim in (0.0, 1.0):
            pill.set_dim_progress(dim)
            img = pill.grab().toImage()
            assert not img.isNull()
    pill.set_label("An unexpectedly long feature discovery label")
    assert not pill.grab().toImage().isNull()


def test_pill_release_outside_does_not_emit(qapp):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.resize(158, 38)
    hits = []
    pill.clicked.connect(lambda: hits.append(True))
    outside = QPointF(500.0, 500.0)
    ev = QMouseEvent(QEvent.MouseButtonRelease, outside,
                     pill.mapToGlobal(outside.toPoint()),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(pill, ev)
    assert hits == []


def test_compact_pill_has_fixed_size_policy(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    from PySide6.QtWidgets import QSizePolicy
    chip = FeaturePill(compact=True)
    assert chip.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed
    assert chip.sizePolicy().verticalPolicy() == QSizePolicy.Fixed


def test_non_compact_pill_expands_horizontally(qapp):
    """The full-width bubble must still stretch across the controls column."""
    from tabs.multitoon._feature_pill import FeaturePill
    from PySide6.QtWidgets import QSizePolicy
    pill = FeaturePill()
    assert pill.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert pill.sizePolicy().verticalPolicy() == QSizePolicy.Fixed


def test_compact_pill_click_emits(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    chip = FeaturePill(compact=True)
    chip.resize(34, 36)
    hits = []
    chip.clicked.connect(lambda: hits.append(True))
    QTest.mouseClick(chip, Qt.LeftButton, pos=QPoint(17, 18))
    assert hits == [True]


def test_compact_pill_paints_no_text_across_envelope(qapp):
    """The chip is sparkle-only. Painting must not depend on the label, so a
    long label must produce a pixel-identical grab to an empty one."""
    from tabs.multitoon._feature_pill import FeaturePill
    from utils.overlay.card_metrics import CardMetrics
    chip = FeaturePill(compact=True)
    for scale in (0.5, 1.0, 1.75):
        m = CardMetrics(scale)
        chip.setFixedSize(m.toggle_w, m.toggle_h)
        chip.set_paint_scale(m.scale)
        for dim in (0.0, 1.0):
            chip.set_dim_progress(dim)
            assert not chip.grab().toImage().isNull()
    m = CardMetrics(1.0)
    chip.setFixedSize(m.toggle_w, m.toggle_h)
    chip.set_paint_scale(1.0)
    chip.set_dim_progress(0.0)
    chip.set_label("")
    empty = chip.grab().toImage()
    chip.set_label("An unexpectedly long feature discovery label")
    assert chip.grab().toImage() == empty


def test_non_compact_pill_still_paints_label(qapp):
    """Regression guard: the full-width bubble keeps its text."""
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.resize(158, 38)
    pill.set_label("")
    empty = pill.grab().toImage()
    pill.set_label("Enable features")
    assert pill.grab().toImage() != empty


# ---- Tab integration: label state machine driven through REAL settings
# writes (the fake fires callbacks like the real SettingsManager), never by
# calling handlers directly (false-green law). ----

from PySide6.QtCore import QObject, Signal
from utils.settings_keys import CLICK_SYNC_ENABLED


class _SignalingFakeSettings:
    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self._callbacks = []

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception:
                pass

    def on_change(self, callback):
        self._callbacks.append(callback)


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

    def get_active_window(self):
        return None


def _tab(qapp, initial=None):
    from tabs.multitoon_tab import MultitoonTab
    sm = _SignalingFakeSettings(initial)
    return MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager()), sm


def test_pills_built_and_placed_in_all_cells(qapp):
    tab, _ = _tab(qapp)
    assert len(tab.feature_pills) == 4
    for i in range(4):
        holder = tab._compact._card_slots[i]["pill_holder"]
        assert holder.itemAt(0).widget() is tab.feature_pills[i]


def test_chips_built_and_placed_in_toggle_row(qapp):
    tab, _ = _tab(qapp)
    assert len(tab.feature_chips) == 4
    for i in range(4):
        row = tab._compact._card_slots[i]["toggle_row"]
        widgets = [row.itemAt(n).widget() for n in range(row.count())]
        assert tab.feature_chips[i] in widgets
        # The chip sits after the three toggles and before the trailing stretch.
        assert widgets.index(tab.feature_chips[i]) == 3
        assert row.itemAt(row.count() - 1).widget() is None   # the stretch


def test_chip_click_opens_popover_for_its_own_slot(qapp):
    tab, _ = _tab(qapp)
    seen = []
    original = tab._open_feature_popover
    tab._open_feature_popover = lambda idx: seen.append(idx)
    try:
        for i in range(4):
            tab.feature_chips[i].clicked.emit()
    finally:
        tab._open_feature_popover = original
    assert seen == [0, 1, 2, 3]


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_chip_is_sized_from_card_metrics(qapp, scale):
    from utils.overlay.card_metrics import CardMetrics
    tab, _ = _tab(qapp)
    try:
        m = CardMetrics(scale)
        tab._compact.apply_metrics(m)
        for chip in tab.feature_chips:
            assert chip.width() == m.toggle_w
            assert chip.height() == m.toggle_h
    finally:
        tab.input_service.shutdown()


def test_chip_receives_paint_scale_from_layout(qapp):
    from utils.overlay.card_metrics import CardMetrics
    tab, _ = _tab(qapp)
    m = CardMetrics(1.5)
    tab._compact.apply_metrics(m)
    assert [chip._scale for chip in tab.feature_chips] == [m.scale] * 4


def test_chip_receives_light_chrome_from_card_brand(qapp):
    tab, _ = _tab(qapp, {"theme": "light"})
    for i in range(4):
        tab._compact.set_card_brand(i, None, enabled=False)
    assert [chip._light_chrome for chip in tab.feature_chips] == [True] * 4


def test_chip_receives_dim_progress_from_card(qapp):
    tab, _ = _tab(qapp)
    progress = 0.375
    for i in range(4):
        cell = tab._compact._cells[tab._compact._slot_to_cell[i]]
        tab._compact._apply_dim_progress(cell, i, progress)
    assert [chip._dim for chip in tab.feature_chips] == [progress] * 4


def test_label_both_off_enable_features(qapp):
    tab, _ = _tab(qapp)
    for pill in tab.feature_pills:
        assert pill.label() == "Enable features"
        assert pill.isHidden() is False


def _visible(widgets):
    return [not w.isHidden() for w in widgets]


def test_both_off_shows_bubble_only(qapp):
    tab, _ = _tab(qapp)
    assert _visible(tab.feature_pills) == [True] * 4
    assert _visible(tab.feature_chips) == [False] * 4
    for pill in tab.feature_pills:
        assert pill.label() == "Enable features"


def test_click_sync_only_shows_chip_only(qapp):
    tab, sm = _tab(qapp)
    sm.set(CLICK_SYNC_ENABLED, True)
    assert _visible(tab.feature_pills) == [False] * 4
    assert _visible(tab.feature_chips) == [True] * 4


def test_keep_alive_only_shows_chip_only(qapp):
    tab, sm = _tab(qapp)
    sm.set("keep_alive_enabled", True)
    assert _visible(tab.feature_pills) == [False] * 4
    assert _visible(tab.feature_chips) == [True] * 4


def test_both_on_hides_bubble_and_chip(qapp):
    tab, sm = _tab(qapp)
    sm.set(CLICK_SYNC_ENABLED, True)
    sm.set("keep_alive_enabled", True)
    assert _visible(tab.feature_pills) == [False] * 4
    assert _visible(tab.feature_chips) == [False] * 4


def test_turning_a_flag_back_off_restores_the_chip(qapp):
    tab, sm = _tab(qapp, {"click_sync_enabled": True, "keep_alive_enabled": True})
    assert _visible(tab.feature_chips) == [False] * 4
    sm.set("keep_alive_enabled", False)
    assert _visible(tab.feature_chips) == [True] * 4
    assert _visible(tab.feature_pills) == [False] * 4


def test_turning_both_flags_off_restores_the_bubble(qapp):
    tab, sm = _tab(qapp, {"click_sync_enabled": True, "keep_alive_enabled": True})
    sm.set("keep_alive_enabled", False)
    sm.set(CLICK_SYNC_ENABLED, False)
    assert _visible(tab.feature_pills) == [True] * 4
    assert _visible(tab.feature_chips) == [False] * 4
    for pill in tab.feature_pills:
        assert pill.label() == "Enable features"


def test_both_on_hides_all_pills(qapp):
    tab, sm = _tab(qapp)
    sm.set(CLICK_SYNC_ENABLED, True)
    sm.set("keep_alive_enabled", True)
    for pill in tab.feature_pills:
        assert pill.isHidden() is True


def test_popover_switch_reveals_controls_on_all_cards(qapp):
    """The payoff moment end to end: the popover's switch write makes the
    click-sync toggle visible on every card via the real settings chain."""
    tab, sm = _tab(qapp)
    assert all(btn.isHidden() for btn in tab.click_sync_buttons)
    tab._open_feature_popover(0)
    tab._feature_popover._on_switch_clicked("sync")
    assert all(not btn.isHidden() for btn in tab.click_sync_buttons)
    tab._feature_popover.hide()


def test_popover_open_syncs_and_reflects_external_change(qapp):
    tab, sm = _tab(qapp)
    tab._open_feature_popover(0)
    assert tab._feature_popover._switches["sync"]._checked is False
    sm.set(CLICK_SYNC_ENABLED, True)   # e.g. Settings page flipped it
    assert tab._feature_popover._switches["sync"]._checked is True
    tab._feature_popover.hide()


def test_popover_anchors_to_the_visible_affordance(qapp):
    """With one feature on, the chip is the visible affordance - anchoring to
    the hidden bubble would place the popover at a stale position."""
    tab, sm = _tab(qapp)
    tab._open_feature_popover(0)          # first call constructs the popover
    tab._feature_popover.hide()
    captured = []
    tab._feature_popover.open_at = lambda anchor, above: captured.append(anchor)

    sm.set(CLICK_SYNC_ENABLED, True)      # chip visible, bubble hidden
    tab._open_feature_popover(0)
    chip = tab.feature_chips[0]
    assert captured[-1].size() == chip.size()
    assert captured[-1].topLeft() == chip.mapToGlobal(chip.rect().topLeft())

    sm.set(CLICK_SYNC_ENABLED, False)     # both off: bubble is visible again
    tab._open_feature_popover(0)
    pill = tab.feature_pills[0]
    assert captured[-1].size() == pill.size()
    assert captured[-1].topLeft() == pill.mapToGlobal(pill.rect().topLeft())


def test_footer_signal_reaches_tab_signal(qapp):
    tab, _ = _tab(qapp)
    hits = []
    tab.features_settings_requested.connect(lambda: hits.append(True))
    tab._open_feature_popover(0)
    tab._feature_popover._footer_btn.click()
    assert hits == [True]
