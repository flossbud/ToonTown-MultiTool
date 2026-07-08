import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from utils.widgets.keysets.movement_key_field import MovementKeyField

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def _press(field, qtkey, text="", modifiers=Qt.NoModifier):
    field.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, qtkey, modifiers, text))

def test_captures_letter_lowercase(app):
    f = MovementKeyField(); f._awaiting = True
    _press(f, Qt.Key_W, "w")
    assert f.get_key() == "w"

def test_captures_space_canonical(app):
    f = MovementKeyField(); f._awaiting = True
    _press(f, Qt.Key_Space, " ")
    assert f.get_key() == "space"

def test_emits_key_captured(app):
    f = MovementKeyField(); f._awaiting = True
    got = []
    f.key_captured.connect(got.append)
    _press(f, Qt.Key_T, "t")
    assert got == ["t"]

def test_locked_blocks_capture(app):
    f = MovementKeyField("w"); f.set_locked(True)
    ev = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    f.mousePressEvent(ev)
    assert f._awaiting is False
    assert f.get_key() == "w"
