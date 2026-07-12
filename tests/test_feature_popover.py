"""FeatureDiscoveryPopover: switches write the app-wide flags through the
settings manager; the Keep-Alive switch is gated by the inline ToS confirm
unless consent was already recorded. The fake settings manager fires
callbacks on set(), mirroring the real SettingsManager contract, so these
tests exercise the same event chain the app uses."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from utils.settings_keys import CLICK_SYNC_ENABLED


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _SignalingFakeSettings:
    """Mirrors utils.settings_manager.SettingsManager's callback contract."""
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


def _popover(sm):
    from tabs.multitoon._feature_popover import FeatureDiscoveryPopover
    return FeatureDiscoveryPopover(sm)


def test_click_sync_switch_writes_flag_both_ways(qapp):
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop._on_switch_clicked("sync")
    assert sm.get(CLICK_SYNC_ENABLED) is True
    pop._on_switch_clicked("sync")
    assert sm.get(CLICK_SYNC_ENABLED) is False


def test_keep_alive_without_consent_opens_confirm_not_flag(qapp):
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    assert sm.get("keep_alive_enabled") is None
    assert pop._tos_panel.isVisibleTo(pop) is True


def test_keep_alive_confirm_records_consent_then_flag(qapp):
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    order = []
    orig_set = sm.set
    sm.set = lambda k, v: (order.append(k), orig_set(k, v))
    pop._on_tos_confirm()
    assert order == ["keep_alive_consent_acknowledged", "keep_alive_enabled"]
    assert sm.get("keep_alive_enabled") is True
    assert pop._tos_panel.isVisibleTo(pop) is False


def test_keep_alive_cancel_writes_nothing(qapp):
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    pop._on_tos_cancel()
    assert sm.get("keep_alive_enabled") is None
    assert sm.get("keep_alive_consent_acknowledged") is None
    assert pop._tos_panel.isVisibleTo(pop) is False


def test_keep_alive_with_prior_consent_flips_directly(qapp):
    sm = _SignalingFakeSettings({"keep_alive_consent_acknowledged": True})
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    assert sm.get("keep_alive_enabled") is True
    assert pop._tos_panel.isVisibleTo(pop) is False


def test_keep_alive_off_is_immediate(qapp):
    sm = _SignalingFakeSettings(
        {"keep_alive_enabled": True, "keep_alive_consent_acknowledged": True})
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    assert sm.get("keep_alive_enabled") is False


def test_sync_from_settings_reflects_flags(qapp):
    sm = _SignalingFakeSettings({CLICK_SYNC_ENABLED: True})
    pop = _popover(sm)
    pop.sync_from_settings()
    assert pop._switches["sync"]._checked is True
    assert pop._switches["ka"]._checked is False


def test_footer_emits_settings_requested(qapp):
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    hits = []
    pop.settings_requested.connect(lambda: hits.append(True))
    pop._footer_btn.click()
    assert hits == [True]


def test_prefer_above_helper(qapp):
    from tabs.multitoon._feature_popover import prefer_above
    assert prefer_above(anchor_center_y=800, screen_center_y=540) is True
    assert prefer_above(anchor_center_y=200, screen_center_y=540) is False


def test_reentrant_sync_during_switch_write_is_safe(qapp):
    """The live tab registers an on_change callback that calls
    sync_from_settings while _on_switch_clicked is still on the stack.
    Must not raise, loop, or corrupt the final state."""
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    sm.on_change(lambda k, v: pop.sync_from_settings())
    pop._on_switch_clicked("sync")
    assert sm.get(CLICK_SYNC_ENABLED) is True
    assert pop._switches["sync"]._checked is True


def test_reopen_resets_tos_panel(qapp):
    from PySide6.QtCore import QRect
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop._on_switch_clicked("ka")
    assert pop._tos_panel.isVisibleTo(pop) is True
    pop.open_at(QRect(100, 100, 158, 38), above=False)
    assert pop._tos_panel.isVisibleTo(pop) is False
    pop.hide()


def _panel_top(pop):
    # Placement asserts target the visible PANEL: the widget itself carries a
    # transparent painted-shadow margin around it.
    return pop.y() + pop._panel.geometry().top()


def _panel_bottom(pop):
    return pop.y() + pop._panel.geometry().bottom()


def test_open_at_places_above_and_below_anchor(qapp):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    # Center the anchor so the popover fits both above and below: offscreen
    # virtual screens are small (800px here), and a low anchor would let the
    # screen-edge clamp pull the below case upward and mask the placement.
    geo = QGuiApplication.primaryScreen().availableGeometry()
    anchor = QRect(geo.center().x() - 79, geo.center().y() - 19, 158, 38)
    pop.open_at(anchor, above=False)
    assert _panel_top(pop) >= anchor.bottom()
    below_y = pop.y()
    pop.hide()
    pop.open_at(anchor, above=True)
    assert _panel_bottom(pop) <= anchor.top()
    assert pop.y() < below_y
    pop.hide()


def test_open_at_clamps_to_screen(qapp):
    """An anchor at the very bottom of the screen forces the clamp branch of
    _reposition: the popover must stay inside availableGeometry."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    geo = QGuiApplication.primaryScreen().availableGeometry()
    # The anchor's CENTER must stay on-screen (screenAt keys the clamp geo
    # off it, as production pill anchors always do); a below-open from this
    # near-bottom anchor still cannot fit and must clamp.
    anchor = QRect(geo.center().x() - 79, geo.bottom() - 60, 158, 38)
    pop.open_at(anchor, above=False)
    assert _panel_top(pop) >= geo.top()
    assert _panel_bottom(pop) <= geo.bottom()
    pop.hide()


def test_tos_confirm_button_never_starved_below_hint(qapp):
    """Regression (live finding): fixed stretch factors starved the confirm
    button below its text width at the box's font metrics, clipping the
    label. The layout must always grant at least the size hint."""
    from PySide6.QtCore import QRect
    sm = _SignalingFakeSettings()
    pop = _popover(sm)
    pop.open_at(QRect(400, 300, 158, 38), above=False)
    pop._on_switch_clicked("ka")   # expand the ToS panel
    qapp.processEvents()
    btn = pop._tos_confirm
    assert btn.width() >= btn.sizeHint().width()
    pop.hide()
