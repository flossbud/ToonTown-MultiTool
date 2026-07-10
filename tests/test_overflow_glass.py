import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_trigger_qss_dark_and_light(qapp):
    from utils.theme_manager import get_overflow_trigger_qss
    dark = get_overflow_trigger_qss(True)
    assert "border-radius: 17px" in dark
    assert "rgba(255, 255, 255, 14)" in dark      # alpha(#fff, 0.055)
    assert "#9a9a9a" in dark and "#dddddd" in dark
    assert 'QToolButton#rail_overflow[open="true"]' in dark
    light = get_overflow_trigger_qss(False)
    assert "rgba(15, 23, 42, 14)" in light
    assert "#64748b" in light and "#334155" in light
    assert 'QToolButton#rail_overflow[open="true"]' in light


def test_popup_v2_theme_rows_and_radius(qapp):
    from utils.widgets.overflow_popup import OverflowPopup
    pop = OverflowPopup()
    pop.add_action("View Logs", lambda: None)
    pop.apply_v2_theme(True)
    row_qss = pop.rows[0].styleSheet()
    assert "min-height: 28px" in row_qss
    assert "font-size: 12.5px" in row_qss
    assert "rgba(255, 255, 255, 18)" in row_qss   # hover alpha(#fff, 0.07)
    assert pop.RADIUS == 10
    pop.apply_v2_theme(False)
    assert "#0f172a" in pop.rows[0].styleSheet()
