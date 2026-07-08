"""MovementKeyField — a QLineEdit that captures a keypress and stores the
canonical key name.

Ported unchanged from tabs/keymap_tab.py (pre-deletion) so it survives that
tab's removal. Emits key_captured(str) where the string is the canonical ABI
value (letters lowercase like "w", "space", "Up", "Alt_L", "Delete", "F1",
"KP_5", etc.).
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import Qt, Signal
from utils.key_registry import NAMED_KEY_REGISTRY, DISPLAY_NAMES_FROM_REGISTRY
from utils.shared_widgets import repolish

# Registry-derived. Adds F1-F12, Home/End/PgUp/PgDn/Insert display names.
DISPLAY_NAMES: dict[str, str] = dict(DISPLAY_NAMES_FROM_REGISTRY)

# Registry-derived. Adds F1-F12, Home/End/PgUp/PgDn/Insert to UI capture.
# getattr(Qt, name) without a default: a typo in qt_key_names becomes an
# import-time AttributeError (the correct fail-fast), not a silently
# un-capturable key. Comprehension scope keeps the loop vars out of the module.
SPECIAL_KEYS: dict[int, str] = {
    int(getattr(Qt, _qt_name)): _kd.canonical
    for _kd in NAMED_KEY_REGISTRY
    if not _kd.numpad_key
    for _qt_name in _kd.qt_key_names
}


def _display(key: str) -> str:
    if not key:
        return "Unset"
    return DISPLAY_NAMES.get(key, key.upper() if len(key) == 1 else key)


# ── Key capture field ──────────────────────────────────────────────────────


class MovementKeyField(QLineEdit):
    key_captured = Signal(str)

    def __init__(self, initial_key: str = "", parent=None):
        super().__init__(parent)
        self._key = initial_key
        self._awaiting = False
        self._locked = False
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumHeight(28)
        self.setFixedWidth(88)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self._update_display()

    def _update_display(self):
        self.setText("Press a key…" if self._awaiting else _display(self._key))
        self.setProperty("awaiting", self._awaiting)
        repolish(self)

    def set_key(self, key: str):
        self._key = key
        self._awaiting = False
        self._update_display()

    def get_key(self) -> str:
        return self._key

    def set_locked(self, locked: bool):
        """A locked field displays its key but never enters capture mode -
        used by the Default set while a game config file drives its keys."""
        self._locked = bool(locked)
        if self._locked:
            self._awaiting = False
        self.setCursor(Qt.ArrowCursor if self._locked else Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus if self._locked else Qt.ClickFocus)
        self.setProperty("locked", "true" if self._locked else "false")
        self._update_display()

    def is_locked(self) -> bool:
        return self._locked

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self._locked:
            return
        self._awaiting = True
        self._update_display()

    # Map Qt key codes to KP_* keysym names when numpad modifier is active
    # Registry-derived. Adds NumLock-off Qt key variants (e.g. Key_Clear for KP_5,
    # Key_Insert for KP_0, Key_End for KP_1, etc.) alongside NumLock-on variants.
    _NUMPAD_KEYS: dict[int, str] = {
        int(getattr(Qt, _qt_name)): _kd.canonical
        for _kd in NAMED_KEY_REGISTRY
        if _kd.numpad_key
        for _qt_name in _kd.qt_key_names
    }

    @staticmethod
    def _vk_is_down(vk: int) -> bool:
        """Windows-only helper: check if a virtual key is currently pressed."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    @staticmethod
    def _side_aware_modifier_key(event) -> str | None:
        """Return side-specific modifier names when available (e.g. Control_R)."""
        k = event.key()
        if k not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt):
            return None

        if sys.platform == "win32":
            vk = int(event.nativeVirtualKey()) if hasattr(event, "nativeVirtualKey") else 0
            sc = int(event.nativeScanCode()) if hasattr(event, "nativeScanCode") else 0

            # Prefer explicit right/left virtual keys when present.
            if k == Qt.Key_Control:
                # Most reliable on Windows: query actual key state.
                if MovementKeyField._vk_is_down(0xA3):  # VK_RCONTROL
                    return "Control_R"
                if MovementKeyField._vk_is_down(0xA2):  # VK_LCONTROL
                    return "Control_L"
                if vk == 0xA3:
                    return "Control_R"
                if vk == 0xA2:
                    return "Control_L"
                # Fallback via scancode (extended right ctrl often reports 0x11D / 285).
                if sc in (0x11D, 285):
                    return "Control_R"
                return "Control_L"

            if k == Qt.Key_Shift:
                if MovementKeyField._vk_is_down(0xA1):  # VK_RSHIFT
                    return "Shift_R"
                if MovementKeyField._vk_is_down(0xA0):  # VK_LSHIFT
                    return "Shift_L"
                if vk == 0xA1:
                    return "Shift_R"
                if vk == 0xA0:
                    return "Shift_L"
                # Typical shift scancodes: left=42, right=54
                if sc == 54:
                    return "Shift_R"
                return "Shift_L"

            if k == Qt.Key_Alt:
                if MovementKeyField._vk_is_down(0xA5):  # VK_RMENU
                    return "Alt_R"
                if MovementKeyField._vk_is_down(0xA4):  # VK_LMENU
                    return "Alt_L"
                if vk == 0xA5:
                    return "Alt_R"
                if vk == 0xA4:
                    return "Alt_L"
                # Extended right alt often reports 0x138 / 312.
                if sc in (0x138, 312):
                    return "Alt_R"
                return "Alt_L"

        # Cross-platform fallback when side info is unavailable.
        if k == Qt.Key_Control:
            return "Control_L"
        if k == Qt.Key_Shift:
            return "Shift_L"
        if k == Qt.Key_Alt:
            return "Alt_L"
        return None

    def keyPressEvent(self, e):
        if not self._awaiting:
            return e.ignore()
        is_numpad = bool(e.modifiers() & Qt.KeypadModifier)
        if is_numpad:
            key = self._NUMPAD_KEYS.get(e.key())
        else:
            key = self._side_aware_modifier_key(e)
            if key is None:
                key = SPECIAL_KEYS.get(e.key())
        if key is None:
            text = e.text()
            if text and text.isprintable():
                key = text.lower() if text.isalpha() else text
        if key:
            self._key = key
            self._awaiting = False
            self._update_display()
            self.clearFocus()
            self.key_captured.emit(key)
        e.accept()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self._awaiting:
            self._awaiting = False
            self._update_display()
