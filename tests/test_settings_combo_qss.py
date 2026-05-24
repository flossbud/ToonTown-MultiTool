import os
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest


@pytest.mark.parametrize("theme_name", ["DARK_THEME", "LIGHT_THEME"])
def test_qcombobox_qss_has_full_segmented_styling(theme_name):
    """Both theme QSS strings must define the full segmented combo style:
    closed state with hover/focus/disabled, drop-down sub-control,
    suppressed native arrow, menu container, and styled menu items."""
    from utils import theme_manager
    qss = getattr(theme_manager, theme_name)

    # Closed state selectors
    assert "QComboBox {" in qss, "missing closed-state base rule"
    assert "QComboBox:hover" in qss, "missing :hover rule"
    assert "QComboBox:focus" in qss, "missing :focus rule"
    assert "QComboBox:disabled" in qss, "missing :disabled rule"

    # Drop-down sub-control (the caret cell)
    assert "QComboBox::drop-down" in qss, "missing ::drop-down sub-control rule"
    assert "subcontrol-origin: padding" in qss, "::drop-down must anchor to padding"
    assert "subcontrol-position: top right" in qss, "::drop-down must sit top-right"

    # Native arrow suppression (our SettingsComboBox.paintEvent draws the chevron)
    assert "QComboBox::down-arrow" in qss, "missing ::down-arrow rule"
    assert "image: none" in qss, "native arrow must be suppressed via image: none"

    # Menu
    assert "QComboBox QAbstractItemView" in qss, "missing menu container rule"
    assert "QComboBox QAbstractItemView::item" in qss, "missing menu item rule"
    assert "QComboBox QAbstractItemView::item:selected" in qss, "missing item hover rule"
