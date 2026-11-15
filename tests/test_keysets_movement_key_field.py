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


# ── Left / right modifier capture ───────────────────────────────────────────

def _press_native(field, qtkey, native_vk):
    field.keyPressEvent(QKeyEvent(
        QKeyEvent.KeyPress, qtkey, Qt.NoModifier, 0, native_vk, 0))


@pytest.mark.parametrize("qtkey,keysym,expected", [
    (Qt.Key_Control, 0xFFE3, "Control_L"),
    (Qt.Key_Control, 0xFFE4, "Control_R"),
    (Qt.Key_Shift,   0xFFE1, "Shift_L"),
    (Qt.Key_Shift,   0xFFE2, "Shift_R"),
    (Qt.Key_Alt,     0xFFE9, "Alt_L"),
    (Qt.Key_Alt,     0xFFEA, "Alt_R"),
])
def test_linux_captures_modifier_side_from_keysym(app, monkeypatch, qtkey, keysym, expected):
    """Qt on X11/Wayland reports the side-specific X keysym as the native
    virtual key. A right-hand modifier must not be stored as its left twin,
    or two sets can never put jump on L Ctrl and R Ctrl respectively."""
    monkeypatch.setattr("utils.widgets.keysets.movement_key_field.sys.platform", "linux")
    f = MovementKeyField(); f._awaiting = True
    _press_native(f, qtkey, keysym)
    assert f.get_key() == expected


def test_linux_unknown_native_key_falls_back_to_left(app, monkeypatch):
    monkeypatch.setattr("utils.widgets.keysets.movement_key_field.sys.platform", "linux")
    f = MovementKeyField(); f._awaiting = True
    _press_native(f, Qt.Key_Control, 0)
    assert f.get_key() == "Control_L"
