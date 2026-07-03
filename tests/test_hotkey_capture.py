import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from utils.hotkey_capture import ChordCaptureButton


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _key(widget, key, mods=Qt.NoModifier, text=""):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, key, mods, text))


def test_records_a_chord(qapp):
    seen = []
    b = ChordCaptureButton("ctrl+1", on_chord=seen.append)
    assert b.text() == "Ctrl+1"
    b.begin_capture()
    _key(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    assert seen == ["ctrl+alt+h"] and b.text() == "Ctrl+Alt+H"


def test_escape_cancels_backspace_clears(qapp):
    seen = []
    b = ChordCaptureButton("F5", on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_Escape)
    assert seen == [] and b.text() == "F5"
    b.begin_capture()
    _key(b, Qt.Key_Backspace)
    assert seen == [None] and b.text() == "Not set"


def test_guardrail_refuses_bare_letter(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_H, Qt.NoModifier, "h")
    assert seen == []                       # refused, still capturing
    assert "modifier" in b.text().lower()   # inline refusal hint
    assert b.is_capturing()


def test_modifier_only_press_keeps_waiting(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_Control, Qt.ControlModifier)
    assert seen == [] and b.is_capturing()


def test_fkey_binds_bare_and_display_forms(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_F5)
    assert seen == ["F5"] and b.text() == "F5"
    assert not b.is_capturing()


def test_ctrl_letter_key_range_path(qapp):
    # Under Ctrl, event.text() is a control char; the Qt.Key_A..Z range path
    # must still resolve the letter.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_H, Qt.ControlModifier, "\x08")
    assert seen == ["ctrl+h"]
