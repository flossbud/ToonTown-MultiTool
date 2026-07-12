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
    pill.set_label("More features")
    assert pill.label() == "More features"


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


def test_label_both_off_enable_features(qapp):
    tab, _ = _tab(qapp)
    for pill in tab.feature_pills:
        assert pill.label() == "Enable features"
        assert pill.isHidden() is False


def test_label_one_on_more_features(qapp):
    tab, sm = _tab(qapp)
    sm.set(CLICK_SYNC_ENABLED, True)
    for pill in tab.feature_pills:
        assert pill.label() == "More features"


def test_both_on_hides_all_pills(qapp):
    tab, sm = _tab(qapp)
    sm.set(CLICK_SYNC_ENABLED, True)
    sm.set("keep_alive_enabled", True)
    for pill in tab.feature_pills:
        assert pill.isHidden() is True


def test_flag_off_again_restores_pill(qapp):
    tab, sm = _tab(qapp, {"click_sync_enabled": True, "keep_alive_enabled": True})
    for pill in tab.feature_pills:
        assert pill.isHidden() is True
    sm.set("keep_alive_enabled", False)
    for pill in tab.feature_pills:
        assert pill.isHidden() is False
        assert pill.label() == "More features"


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


def test_footer_signal_reaches_tab_signal(qapp):
    tab, _ = _tab(qapp)
    hits = []
    tab.features_settings_requested.connect(lambda: hits.append(True))
    tab._open_feature_popover(0)
    tab._feature_popover._footer_btn.click()
    assert hits == [True]
