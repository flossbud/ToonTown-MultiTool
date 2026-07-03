import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from utils.hotkey_capture import ChordCaptureButton
from utils.hotkey_chords import chord_error, parse_chord


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


def test_focus_out_cancels_capture(qapp):
    # Clicking another row/widget mid-capture must cancel like Esc so the
    # app-wide keyboard grab never outlives the user's intent.
    seen = []
    b = ChordCaptureButton("ctrl+1", on_chord=seen.append)
    b.begin_capture()
    assert b.is_capturing()
    b.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert not b.is_capturing()
    assert seen == [] and b.text() == "Ctrl+1"


def test_punctuation_binds_keysym_name(qapp):
    # '+' must bind as the keysym NAME 'plus': a literal '+' key would
    # corrupt the chord string ('alt+shift++') and parse_chord rejects it.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_Plus, Qt.AltModifier | Qt.ShiftModifier, "+")
    assert seen == ["alt+shift+plus"]
    assert b.text() == "Alt+Shift+plus"
    assert not b.is_capturing()
    chord = parse_chord(seen[0])            # round-trips through the parser
    assert chord_error(chord) is None


def test_unmapped_printable_refused_with_feedback(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_section, Qt.ControlModifier, "§")
    assert seen == []                        # refused, no callback
    assert "unsupported" in b.text().lower()
    assert b.is_capturing()


def test_space_and_return_do_not_bind(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _key(b, Qt.Key_Space, Qt.ControlModifier, " ")
    assert seen == [] and b.is_capturing()
    _key(b, Qt.Key_Return, Qt.ControlModifier, "\r")
    assert seen == [] and b.is_capturing()


def test_on_capture_end_fires_on_cancel_paths_only(qapp):
    # Cancelled captures (Esc, focus-out) must notify the owner so it can
    # restore decorations the prompt replaced (Settings failure badges).
    # A SUCCESSFUL capture must not: it writes settings, which already
    # triggers the owner's delayed status push.
    ended = []
    b = ChordCaptureButton("F5", on_chord=lambda *_: None,
                           on_capture_end=lambda: ended.append("end"))
    b.begin_capture()
    _key(b, Qt.Key_Escape)
    assert ended == ["end"]
    b.begin_capture()
    b.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert ended == ["end", "end"]
    b.begin_capture()
    _key(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    assert ended == ["end", "end"]           # success path: no callback
