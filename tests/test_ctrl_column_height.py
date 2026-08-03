"""The controls column must never outgrow the card.

With Keep-Alive on and Click Sync off, the column once stacked toggles + KA
pill + keyset + a full-width bubble (180px) against a 172px portrait, and the
excess spilled out of the card - off the bottom on the top cards, off the top
on the bottom-right card, following each quadrant's vertical alignment. The
bubble now demotes to a chip in the toggle row, capping every state at 132px.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_feature_pill_states import _SignalingFakeSettings, _FakeWindowManager
from utils.settings_keys import CLICK_SYNC_ENABLED

CEILING = 132


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _column_height(tab, i):
    lay = tab._compact._card_slots[i]["ctrl_col"]
    lay.invalidate()
    lay.activate()
    return lay.sizeHint().height()


@pytest.mark.parametrize("click_sync,keep_alive", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_controls_column_never_exceeds_the_ceiling(qapp, click_sync, keep_alive):
    from tabs.multitoon_tab import MultitoonTab
    sm = _SignalingFakeSettings({
        "click_sync_enabled": click_sync,
        "keep_alive_enabled": keep_alive,
    })
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())
    for i in range(4):
        h = _column_height(tab, i)
        assert h <= CEILING, (
            f"slot {i} column is {h}px with click_sync={click_sync} "
            f"keep_alive={keep_alive}; ceiling is {CEILING}px"
        )


def test_keep_alive_only_was_the_regression(qapp):
    """The exact combination that used to reach 180px."""
    from tabs.multitoon_tab import MultitoonTab
    sm = _SignalingFakeSettings({"keep_alive_enabled": True})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())
    assert _column_height(tab, 0) <= CEILING
