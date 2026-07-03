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


def _event(etype, key, mods, text, autorep, sc):
    if sc:
        # Long form carries native params: (type, key, modifiers,
        # nativeScanCode, nativeVirtualKey, nativeModifiers, text,
        # autorep, count) - what real platform events look like.
        return QKeyEvent(etype, key, mods, sc, 0, 0, text, autorep, 1)
    return QKeyEvent(etype, key, mods, text, autorep, 1)   # scancode 0


def _press(widget, key, mods=Qt.NoModifier, text="", autorep=False, sc=0):
    widget.keyPressEvent(_event(QKeyEvent.KeyPress, key, mods, text,
                                autorep, sc))


def _release(widget, key, mods=Qt.NoModifier, text="", autorep=False, sc=0):
    widget.keyReleaseEvent(_event(QKeyEvent.KeyRelease, key, mods, text,
                                  autorep, sc))


def test_records_a_chord_on_release(qapp):
    seen = []
    b = ChordCaptureButton("ctrl+1", on_chord=seen.append)
    assert b.text() == "Ctrl+1"
    b.begin_capture()
    _press(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    assert seen == []                          # held: not committed yet
    assert b.text() == "Ctrl+Alt+H..."         # live would-be chord display
    _release(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    assert seen == ["ctrl+alt+h"] and b.text() == "Ctrl+Alt+H"


def test_escape_cancels_backspace_clears(qapp):
    seen = []
    b = ChordCaptureButton("F5", on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_Escape)
    assert seen == [] and b.text() == "F5"
    b.begin_capture()
    _press(b, Qt.Key_Backspace)
    assert seen == [None] and b.text() == "Not set"


def test_guardrail_refuses_bare_letter(qapp):
    # The guardrail check happens at COMMIT (release), not press.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_H, Qt.NoModifier, "h")
    _release(b, Qt.Key_H, Qt.NoModifier, "h")
    assert seen == []                       # refused, still capturing
    assert "modifier" in b.text().lower()   # inline refusal hint
    assert b.is_capturing()


def test_modifier_only_press_keeps_waiting(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_Control, Qt.ControlModifier)
    assert seen == [] and b.is_capturing()
    _release(b, Qt.Key_Control)             # modifier release never commits
    assert seen == [] and b.is_capturing()


def test_fkey_binds_bare_and_display_forms(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_F5)
    _release(b, Qt.Key_F5)
    assert seen == ["F5"] and b.text() == "F5"
    assert not b.is_capturing()


def test_ctrl_letter_key_range_path(qapp):
    # Under Ctrl, event.text() is a control char; the Qt.Key_A..Z range path
    # must still resolve the letter (press AND release side).
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_H, Qt.ControlModifier, "\x08")
    _release(b, Qt.Key_H, Qt.ControlModifier, "\x08")
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


def test_focus_out_resets_held_tracking(qapp):
    # A key held across a focus-out must not commit on a later capture's
    # release: cancel clears the held/max tracking.
    seen = []
    b = ChordCaptureButton("ctrl+1", on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    b.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    b.begin_capture()
    _release(b, Qt.Key_T, Qt.ControlModifier, "t")   # stale release: ignored
    assert seen == [] and b.is_capturing()


def test_punctuation_binds_keysym_name(qapp):
    # '+' must bind as the keysym NAME 'plus': a literal '+' key would
    # corrupt the chord string ('alt+shift++') and parse_chord rejects it.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_Plus, Qt.AltModifier | Qt.ShiftModifier, "+")
    _release(b, Qt.Key_Plus, Qt.AltModifier | Qt.ShiftModifier, "+")
    assert seen == ["alt+shift+plus"]
    assert b.text() == "Alt+Shift+plus"
    assert not b.is_capturing()
    chord = parse_chord(seen[0])            # round-trips through the parser
    assert chord_error(chord) is None


def test_unmapped_printable_refused_with_feedback(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_section, Qt.ControlModifier, "§")
    assert seen == []                        # refused, no callback
    assert "unsupported" in b.text().lower()
    assert b.is_capturing()


def test_space_and_return_do_not_bind(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_Space, Qt.ControlModifier, " ")
    assert seen == [] and b.is_capturing()
    _press(b, Qt.Key_Return, Qt.ControlModifier, "\r")
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
    _press(b, Qt.Key_Escape)
    assert ended == ["end"]
    b.begin_capture()
    b.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert ended == ["end", "end"]
    b.begin_capture()
    _press(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    _release(b, Qt.Key_H, Qt.ControlModifier | Qt.AltModifier, "h")
    assert ended == ["end", "end"]           # success path: no callback


def test_multikey_capture_commits_max_held_set_on_release(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ShiftModifier, "T")
    _press(b, Qt.Key_1, Qt.ShiftModifier, "1")   # both held now
    assert b.text() == "Shift+1+T..."            # live two-key display
    _release(b, Qt.Key_1, Qt.ShiftModifier)
    assert seen == ["shift+1+t"]
    assert not b.is_capturing()


def test_third_simultaneous_key_refused(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    _press(b, Qt.Key_1, Qt.ControlModifier, "1")
    _press(b, Qt.Key_2, Qt.ControlModifier, "2")
    assert "at most two" in b.text().lower()
    _release(b, Qt.Key_1, Qt.ControlModifier)
    assert seen == ["ctrl+1+t"]                   # third key never joined
    assert not b.is_capturing()


def test_autorepeat_release_does_not_commit(qapp):
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    _press(b, Qt.Key_T, Qt.ControlModifier, "t", autorep=True)
    _release(b, Qt.Key_T, Qt.ControlModifier, autorep=True)
    assert seen == [] and b.is_capturing()
    _release(b, Qt.Key_T, Qt.ControlModifier)
    assert seen == ["ctrl+t"]
    assert not b.is_capturing()


def test_guardrail_refusal_resets_tracking_for_retry(qapp):
    # After a bare-letter refusal the user can immediately record a valid
    # chord in the SAME capture; the stale key's later release is inert.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.NoModifier, "t")
    _press(b, Qt.Key_1, Qt.NoModifier, "1")
    _release(b, Qt.Key_T, Qt.NoModifier, "t")    # commit: no modifier -> refused
    assert seen == [] and "modifier" in b.text().lower()
    assert b.is_capturing()
    _release(b, Qt.Key_1, Qt.NoModifier, "1")    # stale after reset: ignored
    assert seen == [] and b.is_capturing()
    _press(b, Qt.Key_H, Qt.ControlModifier, "h")
    _release(b, Qt.Key_H, Qt.ControlModifier, "h")
    assert seen == ["ctrl+h"]


def test_shifted_symbol_records_base_key_by_scancode(qapp):
    # Real shift+1 on a US layout arrives as Key_Exclam text "!"; it must
    # record the BASE key "1" or the flagship shift+t+1 chord could never
    # be captured live.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ShiftModifier, "T", sc=28)
    _press(b, Qt.Key_Exclam, Qt.ShiftModifier, "!", sc=2)
    _release(b, Qt.Key_Exclam, Qt.ShiftModifier, "!", sc=2)
    assert seen == ["shift+1+t"]
    assert not b.is_capturing()


def test_modifier_first_release_matches_by_scancode(qapp):
    # Press shift+= (records "plus"); if shift lifts BEFORE '=', the release
    # reports Key_Equal text "=" - a different symbol on the SAME physical
    # key. The scancode identity must match the held entry and commit the
    # chord as captured.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_Plus, Qt.ShiftModifier, "+", sc=13)
    _release(b, Qt.Key_Equal, Qt.NoModifier, "=", sc=13)
    assert seen == ["shift+plus"]
    assert not b.is_capturing()


def test_first_pressed_key_released_first_commits_full_set(qapp):
    # Either release order commits the full held set, not just the survivor.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    _press(b, Qt.Key_1, Qt.ControlModifier, "1")
    _release(b, Qt.Key_T, Qt.ControlModifier, "t")   # FIRST-pressed leaves first
    assert seen == ["ctrl+1+t"]
    assert not b.is_capturing()


def test_escape_mid_hold_stale_release_is_inert(qapp):
    # Esc while a key is held cancels AND clears tracking: the stale release
    # arriving in a fresh capture must not commit anything.
    seen = []
    b = ChordCaptureButton("ctrl+1", on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    _press(b, Qt.Key_Escape)                         # cancel mid-hold
    assert not b.is_capturing() and b.text() == "Ctrl+1"
    b.begin_capture()
    _release(b, Qt.Key_T, Qt.ControlModifier, "t")   # stale: ignored
    assert seen == [] and b.is_capturing()


def test_refused_third_key_release_never_commits(qapp):
    # The refused third key never joined the held set, so its release is
    # inert; the chord still commits from the two captured keys.
    seen = []
    b = ChordCaptureButton(None, on_chord=seen.append)
    b.begin_capture()
    _press(b, Qt.Key_T, Qt.ControlModifier, "t")
    _press(b, Qt.Key_1, Qt.ControlModifier, "1")
    _press(b, Qt.Key_2, Qt.ControlModifier, "2")     # refused (third)
    _release(b, Qt.Key_2, Qt.ControlModifier, "2")   # inert: never held
    assert seen == [] and b.is_capturing()
    _release(b, Qt.Key_1, Qt.ControlModifier, "1")
    assert seen == ["ctrl+1+t"]
    assert not b.is_capturing()
