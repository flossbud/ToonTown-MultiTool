import os
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QStyledItemDelegate


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def test_current_value_delegate_can_be_installed_on_combobox(app):
    from utils.shared_widgets import _CurrentValueDelegate
    cb = QComboBox()
    cb.addItems(["A", "B", "C"])
    delegate = _CurrentValueDelegate(cb)
    cb.setItemDelegate(delegate)
    assert cb.itemDelegate() is delegate
    assert isinstance(delegate, QStyledItemDelegate)


def test_settings_combobox_auto_installs_current_value_delegate(app):
    from utils.shared_widgets import SettingsComboBox, _CurrentValueDelegate
    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    assert isinstance(cb.itemDelegate(), _CurrentValueDelegate)


def test_settings_combobox_is_a_qcombobox(app):
    from utils.shared_widgets import SettingsComboBox
    cb = SettingsComboBox()
    assert isinstance(cb, QComboBox)


def test_settings_combobox_preserves_currentindex_semantics(app):
    from utils.shared_widgets import SettingsComboBox
    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(2)
    assert cb.currentIndex() == 2
    assert cb.currentText() == "C"


def test_current_value_delegate_paints_dot_on_current_row(app):
    """Render the menu's current row to a QPixmap and confirm the dot's
    pixel matches the combo's configured accent color."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(1)  # "B"

    model = cb.model()
    delegate = cb.itemDelegate()

    # Render row B (current).
    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))  # opaque background so the dot is unambiguous
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    delegate.paint(painter, option, model.index(1, 0))
    painter.end()

    # Dot center is at (right - 12 - 3, height/2) = (105, 14).
    img = pm.toImage()
    sample = img.pixelColor(105, 14)
    # Default accent is #0077ff (R=0, G=119, B=255). Antialiasing softens
    # edges, but the center pixel should be at or very near the pure color.
    assert sample.red() < 30, f"expected R≈0, got R={sample.red()}"
    assert 90 < sample.green() < 140, f"expected G≈119, got G={sample.green()}"
    assert sample.blue() > 220, f"expected B≈255, got B={sample.blue()}"


def test_set_theme_colors_changes_dot_to_configured_accent(app):
    """Light theme's accent_blue_btn is #2563eb, distinct from the dark
    default #0077ff. set_theme_colors must propagate to the painted dot."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B"])
    cb.setCurrentIndex(0)
    cb.set_theme_colors(accent="#2563eb")  # light-theme accent

    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    cb.itemDelegate().paint(painter, option, cb.model().index(0, 0))
    painter.end()

    img = pm.toImage()
    sample = img.pixelColor(105, 14)
    # #2563eb is (R=37, G=99, B=235) — distinct from default #0077ff (R=0, G=119, B=255).
    # Green and blue differ from the default by enough that this catches
    # any regression where the dot ignores set_theme_colors.
    assert sample.green() < 110, f"expected G<110 (light accent), got G={sample.green()}"
    assert sample.red() > 20, f"expected R>20 (light accent), got R={sample.red()}"


def test_current_value_delegate_does_not_paint_dot_on_non_current_row(app):
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(1)  # "B" is current

    model = cb.model()
    delegate = cb.itemDelegate()

    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    delegate.paint(painter, option, model.index(2, 0))  # row "C", NOT current
    painter.end()

    img = pm.toImage()
    sample = img.pixelColor(120 - 15, 14)
    # No dot — should still be background-ish (low blue).
    assert sample.blue() < 100, f"expected no dot, got B={sample.blue()}"
