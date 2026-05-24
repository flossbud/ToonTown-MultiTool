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
