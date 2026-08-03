"""FeaturePill chip unit behavior and MultitoonTab integration."""
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


def test_chip_click_emits(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    chip = FeaturePill()
    chip.resize(34, 36)
    hits = []
    chip.clicked.connect(lambda: hits.append(True))
    QTest.mouseClick(chip, Qt.LeftButton, pos=QPoint(17, 18))
    assert hits == [True]


def test_chip_dim_and_scale_apis(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    chip = FeaturePill()
    chip.set_dim_progress(0.5)
    chip.set_dim_progress(2.0)   # clamps, no raise
    chip.set_paint_scale(1.5)
    chip.set_paint_scale(1.5)    # idempotent, no raise


def test_chip_paint_smoke_across_scale_envelope(qapp):
    """Exercise the sparkle-only paint path across CardMetrics' scale range."""
    from tabs.multitoon._feature_pill import FeaturePill
    from utils.overlay.card_metrics import CardMetrics
    chip = FeaturePill()
    for scale in (0.5, 1.0, 1.75):
        m = CardMetrics(scale)
        chip.setFixedSize(m.toggle_w, m.toggle_h)
        chip.set_paint_scale(m.scale)
        for dim in (0.0, 1.0):
            chip.set_dim_progress(dim)
            img = chip.grab().toImage()
            assert not img.isNull()


def test_chip_release_outside_does_not_emit(qapp):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from tabs.multitoon._feature_pill import FeaturePill
    chip = FeaturePill()
    chip.resize(34, 36)
    hits = []
    chip.clicked.connect(lambda: hits.append(True))
    outside = QPointF(500.0, 500.0)
    ev = QMouseEvent(QEvent.MouseButtonRelease, outside,
                     chip.mapToGlobal(outside.toPoint()),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(chip, ev)
    assert hits == []


def test_chip_has_fixed_size_policy(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    from PySide6.QtWidgets import QSizePolicy
    chip = FeaturePill()
    assert chip.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed
    assert chip.sizePolicy().verticalPolicy() == QSizePolicy.Fixed


# ---- Tab integration -----------------------------------------------------

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


def _visible(widgets):
    return [not w.isHidden() for w in widgets]


@pytest.mark.parametrize("click_sync,keep_alive", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_feature_chip_is_visible_for_every_flag_combination(
        qapp, click_sync, keep_alive):
    tab, _ = _tab(qapp, {
        CLICK_SYNC_ENABLED: click_sync,
        "keep_alive_enabled": keep_alive,
    })
    assert _visible(tab.feature_chips) == [True] * 4


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


def test_popover_anchors_to_the_chip(qapp):
    tab, _ = _tab(qapp)
    tab._open_feature_popover(0)          # first call constructs the popover
    tab._feature_popover.hide()
    captured = []
    tab._feature_popover.open_at = lambda anchor, above: captured.append(anchor)

    tab._open_feature_popover(0)
    chip = tab.feature_chips[0]
    assert captured[-1].size() == chip.size()
    assert captured[-1].topLeft() == chip.mapToGlobal(chip.rect().topLeft())


def test_footer_signal_reaches_tab_signal(qapp):
    tab, _ = _tab(qapp)
    hits = []
    tab.features_settings_requested.connect(lambda: hits.append(True))
    tab._open_feature_popover(0)
    tab._feature_popover._footer_btn.click()
    assert hits == [True]
