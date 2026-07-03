"""Press-to-record chord button for the Settings Hotkeys card.

Click -> capture mode (Qt keyboard grab so the chord cannot leak into the
app or fire other widgets' shortcuts). The chord COMMITS on the first key
RELEASE: it is the set of simultaneously-held keys (up to TWO
non-modifier keys, a third is refused inline) plus the modifiers held at
the last key press, so 'shift held + t held + 1 pressed' records
'shift+1+t' in either press order. Held keys are tracked by PHYSICAL
identity (native scancode + virtual-key pair) so a key whose reported
symbol changes when a modifier lifts first ('+' releasing as '=') still
matches its press.
While keys are held the button shows the would-be chord live with a
trailing '...'. Esc cancels, Backspace clears the binding
(on_chord(None)), a guardrail-violating chord shows the refusal inline
and keeps capturing. on_chord receives the canonical chord string.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from utils.hotkey_chords import Chord, chord_error, format_chord

_QT_MODS = ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
            (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "super"))
_MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Shift,
             Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R}
_MOD_NAMES = frozenset(("ctrl", "alt", "shift", "super"))

# Punctuation binds by X keysym NAME so the emitted chord round-trips
# through parse_chord (a literal '+' key would corrupt the chord string).
_PUNCT_KEYSYMS = {
    "+": "plus", "-": "minus", "=": "equal", ",": "comma", ".": "period",
    "/": "slash", "\\": "backslash", ";": "semicolon", "'": "apostrophe",
    "[": "bracketleft", "]": "bracketright", "`": "grave",
}

# Shifted symbols record their BASE key (US-layout assumption, matching the
# keysym-name vocabulary above): real shift+1 arrives as Key_Exclam text "!"
# and must record "1", or the flagship shift+t+1 chord could never be
# captured. "+" is deliberately absent: it stays a bindable key of its own
# via _PUNCT_KEYSYMS -> "plus".
_SHIFTED_US = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
               "&": "7", "*": "8", "(": "9", ")": "0", "~": "grave",
               "_": "minus", "{": "bracketleft", "}": "bracketright",
               "|": "backslash", ":": "semicolon", "\"": "apostrophe",
               "<": "comma", ">": "period", "?": "slash"}


def _display(chord_text: str | None) -> str:
    """Human form of a canonical chord, per part: 'ctrl+alt+h' ->
    'Ctrl+Alt+H', 'shift+1+t' -> 'Shift+1+T'."""
    if not chord_text:
        return "Not set"
    parts = []
    for p in chord_text.split("+"):
        if p in _MOD_NAMES:
            parts.append(p.capitalize())     # the four modifier names
        elif len(p) == 1:
            parts.append(p.upper())          # single key: H, 1
        else:
            parts.append(p)                  # F-keys / keysym names verbatim
    return "+".join(parts)


def _key_name(event) -> str | None:
    """The chord key for a Qt key event, or None if unbindable."""
    key = event.key()
    if Qt.Key_F1 <= key <= Qt.Key_F35:
        return f"F{key - Qt.Key_F1 + 1}"
    # Explicit ranges first: under Ctrl, event.text() is a control char.
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("a") + key - Qt.Key_A)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + key - Qt.Key_0)
    text = event.text()
    if len(text) == 1 and text.isprintable() and not text.isspace():
        base = _SHIFTED_US.get(text)
        if base is not None:
            return base                      # shifted symbol -> base key
        if text.isascii() and text.isalnum():
            return text.lower()
        return _PUNCT_KEYSYMS.get(text)      # unmapped -> None (refused)
    return None


def _identity(event, name):
    """Physical-key identity for held-set tracking. The native PAIR is
    required: cocoa hardcodes nativeScanCode() to 1 for every key (only
    nativeVirtualKey distinguishes them), X11/Windows populate scancode.
    Synthetic short-form events are (0, 0) -> name fallback (offscreen
    tests). kVK_ANSI_A == 0 on cocoa is fine: (1, 0) != (0, 0)."""
    native = (event.nativeScanCode(), event.nativeVirtualKey())
    if native != (0, 0):
        return native
    return f"name:{name}" if name is not None else None


class ChordCaptureButton(QPushButton):
    """One binding row's press-to-record control."""

    def __init__(self, chord_text: str | None, on_chord, parent=None,
                 *, on_capture_end=None):
        super().__init__(_display(chord_text), parent)
        self._chord_text = chord_text
        self._on_chord = on_chord
        # Fired when a capture ends WITHOUT a chord (Esc / focus-out), so
        # the owner can restore decorations the capture prompt replaced
        # (e.g. the Settings card's failure badges). Deliberately NOT fired
        # on the success path: a successful capture writes settings, which
        # already triggers the owner's delayed status push.
        self._on_capture_end = on_capture_end
        self._capturing = False
        # {identity: canonical key name} in press order, physically held.
        self._held: dict = {}
        self._mods_at_last_press: frozenset = frozenset()
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
        self._reset_held()
        # Take focus BEFORE grabbing: if another row is mid-capture, its
        # focusOutEvent cancels (and releases its grab) right now, so our
        # grab below is never stomped by that release.
        self.setFocus(Qt.MouseFocusReason)
        self.setText("Press a chord... (Esc cancels, Backspace clears)")
        self.grabKeyboard()

    def _end_capture(self) -> None:
        self._capturing = False
        self._reset_held()
        self.releaseKeyboard()

    def _reset_held(self) -> None:
        self._held = {}
        self._mods_at_last_press = frozenset()

    def focusOutEvent(self, event) -> None:
        # Losing focus while capturing = the user moved on (clicked another
        # widget/row, switched Settings pages): cancel like Esc so the
        # app-wide keyboard grab can never outlive the user's intent.
        if self._capturing:
            self._end_capture()
            self.set_chord(self._chord_text)
            if self._on_capture_end is not None:
                self._on_capture_end()
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:
        if not self._capturing:
            return super().keyPressEvent(event)
        if event.isAutoRepeat():
            return                               # held key echo: not a press
        key = event.key()
        if key == Qt.Key_Escape:
            self._end_capture()
            self.set_chord(self._chord_text)     # unchanged
            if self._on_capture_end is not None:
                self._on_capture_end()
            return
        if key == Qt.Key_Backspace:
            self._end_capture()
            self.set_chord(None)
            self._on_chord(None)
            return
        if key in _MOD_KEYS:
            return                               # wait for a terminal key
        name = _key_name(event)
        if name is None:
            self.setText("Refused: unsupported key - use letters, digits, "
                         "F-keys, or common punctuation")
            return                               # keep capturing, held intact
        identity = _identity(event, name)
        if identity not in self._held:
            if len(self._held) >= 2:
                self.setText("Refused: chords support at most two keys")
                return                           # third key never joins
            self._held[identity] = name
        self._mods_at_last_press = frozenset(
            m for qt_m, m in _QT_MODS if event.modifiers() & qt_m)
        would_be = Chord(mods=self._mods_at_last_press,
                         keys=frozenset(self._held.values()))
        self.setText(_display(format_chord(would_be)) + "...")

    def keyReleaseEvent(self, event) -> None:
        if not self._capturing:
            return super().keyReleaseEvent(event)
        if event.isAutoRepeat():
            return                               # held key echo: not a release
        identity = _identity(event, _key_name(event))
        if identity is None or identity not in self._held:
            return                               # modifier/stale/unbound key
        # First release of a captured key: the held set is at its maximum
        # RIGHT NOW (commit happens before any captured key leaves), so the
        # chord keys are exactly the held names before removal.
        keys = frozenset(self._held.values())
        del self._held[identity]
        chord = Chord(mods=self._mods_at_last_press, keys=keys)
        err = chord_error(chord)
        if err is not None:
            self.setText(f"Refused: {err}")
            self._reset_held()
            return                               # keep capturing, retry OK
        text = format_chord(chord)
        self._end_capture()
        self.set_chord(text)
        self._on_chord(text)


# Public alias: the Settings Hotkeys card renders chords in user-facing
# prose (the steal prompt) with the same display form the button uses.
display_chord = _display
