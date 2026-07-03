"""Press-to-record chord button for the Settings Hotkeys card.

Click -> capture mode (Qt keyboard grab so the chord cannot leak into the
app or fire other widgets' shortcuts). Esc cancels, Backspace clears the
binding (on_chord(None)), a guardrail-violating chord shows the refusal
inline and keeps capturing. on_chord receives the canonical chord string.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from utils.hotkey_chords import Chord, chord_error, format_chord

_QT_MODS = ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
            (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "super"))
_MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Shift,
             Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R}


def _display(chord_text: str | None) -> str:
    """Human form of a canonical chord: 'ctrl+alt+h' -> 'Ctrl+Alt+H'."""
    if not chord_text:
        return "Not set"
    parts = []
    for p in chord_text.split("+"):
        if p.startswith("F") and p[1:].isdigit():
            parts.append(p)                  # F-keys stay as-is
        elif len(p) == 1:
            parts.append(p.upper())          # single key: H, 1
        else:
            parts.append(p.capitalize())     # modifier / keysym name
    return "+".join(parts)


def _key_name(event) -> str | None:
    """The chord key for a Qt key event, or None if untranslatable."""
    key = event.key()
    if Qt.Key_F1 <= key <= Qt.Key_F35:
        return f"F{key - Qt.Key_F1 + 1}"
    # Explicit ranges first: under Ctrl, event.text() is a control char.
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("a") + key - Qt.Key_A)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + key - Qt.Key_0)
    text = event.text()
    if text and text.isprintable() and not text.isspace():
        return text.lower()
    return None


class ChordCaptureButton(QPushButton):
    """One binding row's press-to-record control."""

    def __init__(self, chord_text: str | None, on_chord, parent=None):
        super().__init__(_display(chord_text), parent)
        self._chord_text = chord_text
        self._on_chord = on_chord
        self._capturing = False
        self.clicked.connect(self.begin_capture)

    def is_capturing(self) -> bool:
        return self._capturing

    def set_chord(self, chord_text: str | None) -> None:
        self._chord_text = chord_text
        self.setText(_display(chord_text))

    def begin_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self.setText("Press a chord... (Esc cancels, Backspace clears)")
        self.grabKeyboard()

    def _end_capture(self) -> None:
        self._capturing = False
        self.releaseKeyboard()

    def keyPressEvent(self, event) -> None:
        if not self._capturing:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_Escape:
            self._end_capture()
            self.set_chord(self._chord_text)     # unchanged
            return
        if key == Qt.Key_Backspace:
            self._end_capture()
            self.set_chord(None)
            self._on_chord(None)
            return
        if key in _MOD_KEYS:
            return                               # wait for the terminal key
        name = _key_name(event)
        if name is None:
            return                               # untranslatable: keep waiting
        mods = frozenset(m for qt_m, m in _QT_MODS
                         if event.modifiers() & qt_m)
        chord = Chord(mods=mods, key=name)
        err = chord_error(chord)
        if err is not None:
            self.setText(f"Refused: {err}")
            return                               # keep capturing
        text = format_chord(chord)
        self._end_capture()
        self.set_chord(text)
        self._on_chord(text)
