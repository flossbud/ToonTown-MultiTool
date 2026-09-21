"""The four-item toggle row must fit inside the fixed controls column."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_feature_pill_states import _SignalingFakeSettings, _FakeWindowManager
from utils.overlay.card_metrics import CardMetrics
from utils.settings_keys import CLICK_SYNC_ENABLED


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize("scale", [0.5, 0.52, 0.84, 1.0, 1.08, 1.4, 1.75])
def test_four_item_toggle_row_fits_controls_column(qapp, scale):
    from tabs.multitoon_tab import MultitoonTab

    settings = _SignalingFakeSettings({
        CLICK_SYNC_ENABLED: True,
        "keep_alive_enabled": False,
    })
    tab = MultitoonTab(
        settings_manager=settings,
        window_manager=_FakeWindowManager(),
    )
    try:
        metrics = CardMetrics(scale)
        tab._compact.apply_metrics(metrics)
        qapp.processEvents()

        row = tab._compact._card_slots[0]["toggle_row"]
        expected_widgets = (
            tab.toon_buttons[0],
            tab.chat_buttons[0],
            tab.click_sync_buttons[0],
            tab.feature_chips[0],
        )
        assert all(not widget.isHidden() for widget in expected_widgets)

        row.invalidate()
        row.activate()
        required_width = max(row.sizeHint().width(), row.minimumSize().width())
        assert required_width <= metrics.ctrl_w, (
            f"scale {metrics.scale:.2f} toggle row needs {required_width}px; "
            f"controls column has {metrics.ctrl_w}px"
        )
    finally:
        tab.input_service.shutdown()
