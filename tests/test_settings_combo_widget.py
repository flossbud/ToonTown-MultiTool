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
    accent-blue pixel appears on the right edge."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(1)  # "B"

    model = cb.model()
    delegate = cb.itemDelegate()

    # Render the row for index B (current).
    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))  # opaque background so we can detect non-bg pixels
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    delegate.paint(painter, option, model.index(1, 0))
    painter.end()

    # Sample pixel near the right edge, vertically centered.
    img = pm.toImage()
    # The dot is right-aligned ~12px from right, ~6px diameter, vertically centered.
    sample = img.pixelColor(120 - 15, 14)
    # Should be blue-ish (R<100, G<150, B>180) — not pure black.
    assert sample.red() < 100, f"expected blue dot, got R={sample.red()}"
    assert sample.blue() > 180, f"expected blue dot, got B={sample.blue()}"


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
