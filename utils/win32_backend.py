"""
Win32-based input backend for ToonTown MultiTool.

Replaces Xlib calls with pywin32 (win32gui, win32api, win32process, win32con).
Uses PostMessage to send keystrokes to background windows without stealing focus.
"""

from __future__ import annotations

try:
    import win32api
    import win32con
    import win32gui
    import win32process

    VK_MAP = {
        'space': win32con.VK_SPACE,
        'Return': win32con.VK_RETURN,
        'BackSpace': win32con.VK_BACK,
        'Tab': win32con.VK_TAB,
        'Escape': win32con.VK_ESCAPE,
        'Delete': win32con.VK_DELETE,
        'Up': win32con.VK_UP,
        'Down': win32con.VK_DOWN,
        'Left': win32con.VK_LEFT,
        'Right': win32con.VK_RIGHT,
        # Navigation cluster (extended keys per Win32 spec)
        'Home':   win32con.VK_HOME,
        'End':    win32con.VK_END,
        'Prior':  win32con.VK_PRIOR,   # Page Up
        'Next':   win32con.VK_NEXT,    # Page Down
        'Insert': win32con.VK_INSERT,
        # Function keys
        'F1':  win32con.VK_F1,  'F2':  win32con.VK_F2,  'F3':  win32con.VK_F3,
        'F4':  win32con.VK_F4,  'F5':  win32con.VK_F5,  'F6':  win32con.VK_F6,
        'F7':  win32con.VK_F7,  'F8':  win32con.VK_F8,  'F9':  win32con.VK_F9,
        'F10': win32con.VK_F10, 'F11': win32con.VK_F11, 'F12': win32con.VK_F12,
        # Numpad
        'KP_0': win32con.VK_NUMPAD0,
        'KP_1': win32con.VK_NUMPAD1,
        'KP_2': win32con.VK_NUMPAD2,
        'KP_3': win32con.VK_NUMPAD3,
        'KP_4': win32con.VK_NUMPAD4,
        'KP_5': win32con.VK_NUMPAD5,
        'KP_6': win32con.VK_NUMPAD6,
        'KP_7': win32con.VK_NUMPAD7,
        'KP_8': win32con.VK_NUMPAD8,
        'KP_9': win32con.VK_NUMPAD9,
        'KP_Decimal': win32con.VK_DECIMAL,
        'KP_Enter': win32con.VK_RETURN,
        'KP_Add': win32con.VK_ADD,
        'KP_Subtract': win32con.VK_SUBTRACT,
        'KP_Multiply': win32con.VK_MULTIPLY,
        'KP_Divide': win32con.VK_DIVIDE,
        'minus': 0xBD,      # VK_OEM_MINUS
        'equal': 0xBB,      # VK_OEM_PLUS
        'bracketleft': 0xDB, # VK_OEM_4
        'bracketright': 0xDD,# VK_OEM_6
        'backslash': 0xDC,  # VK_OEM_5
        'semicolon': 0xBA,  # VK_OEM_1
        'apostrophe': 0xDE, # VK_OEM_7
        'comma': 0xBC,      # VK_OEM_COMMA
        'period': 0xBE,     # VK_OEM_PERIOD
        'slash': 0xBF,      # VK_OEM_2
        'grave': 0xC0,      # VK_OEM_3
        '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
        '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39, '0': 0x30,
    }
    for c in 'abcdefghijklmnopqrstuvwxyz':
        VK_MAP[c] = ord(c.upper())
except ImportError:
    # Not on Windows (or pywin32 absent): the module stays importable so
    # cross-platform unit tests can exercise the pure mouse helpers; the
    # key path needs the real pywin32 and is only reached on Windows.
    win32api = win32con = win32gui = win32process = None
    VK_MAP = {}

# Real Windows keystrokes for L/R modifiers deliver the GENERIC virtual key
# code (VK_CONTROL=0x11, VK_SHIFT=0x10, VK_MENU=0x12) as wparam — NOT the
# L/R-specific VK_LCONTROL/VK_RCONTROL/etc. The L/R distinction lives in the
# lparam scan code + extended-key bit.
#
# Verified against a real WindowProc + SendInput baseline.
#
# Posting VK_LCONTROL through PostMessage only sets Panda3D's
# KeyboardButton::lcontrol() (via lookup_key); TTR's "jump" / "walk" /
# "map" bindings poll the GENERIC control / shift / alt button, which is
# only set when wparam == VK_CONTROL. That's why the v2.2.0 extended-bit
# Right Ctrl "fix" still didn't move toons — it patched lparam but left
# wparam wrong.
#
# Tuple is (wparam_vk, lparam_scan_code, extended_bit).
WIN32_MODIFIER_OVERRIDES = {
    'Control_L': (0x11, 0x1D, False),
    'Control_R': (0x11, 0x1D, True),
    'Shift_L':   (0x10, 0x2A, False),
    'Shift_R':   (0x10, 0x36, False),
    'Alt_L':     (0x12, 0x38, False),
    'Alt_R':     (0x12, 0x38, True),
}

# Map common Windows nokeysym pynput KeyCode char overrides to standardized strings
VK_TO_KEYSYM = {
    96: 'KP_0', 97: 'KP_1', 98: 'KP_2', 99: 'KP_3', 100: 'KP_4',
    101: 'KP_5', 102: 'KP_6', 103: 'KP_7', 104: 'KP_8', 105: 'KP_9',
    106: 'KP_Multiply', 107: 'KP_Add', 109: 'KP_Subtract', 110: 'KP_Decimal', 111: 'KP_Divide'
}

# Win32 "extended keys" require bit 24 of lparam set on WM_KEYDOWN/WM_KEYUP.
# Without it, hosts that read scan-code-derived state (Panda3D / TTR) ignore
# the event. List per Microsoft docs (KEYBDINPUT.dwFlags KEYEVENTF_EXTENDEDKEY
# documentation): arrow keys, Insert, Delete, Home, End, PageUp/PageDown,
# numpad divide and Enter.
#
# Right-side modifiers (Control_R, Alt_R) are NOT listed here even though
# they are extended keys at the OS level. They are handled exclusively
# through WIN32_MODIFIER_OVERRIDES (which encodes the extended bit in its
# own tuple), and _send branches on the override table before consulting
# EXTENDED_KEYSYMS — duplicating them would be dead code.
EXTENDED_KEYSYMS = frozenset({
    'Up', 'Down', 'Left', 'Right',
    'Insert', 'Delete', 'Home', 'End',
    'Prior', 'Next',  # PageUp / PageDown
    'KP_Divide', 'KP_Enter',
})

# ── mouse injection (click sync) ────────────────────────────────────────
# Message/flag literals instead of win32con so the mouse helpers are
# unit-testable off-Windows (win32con only exists under pywin32).
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
_X_BUTTON1_MASK = 0x100  # the service's X-style state mask for button 1


def pack_mouse_lparam(x: int, y: int) -> int:
    """Client coords -> mouse-message lParam (LOWORD x, HIWORD y). Both
    halves masked to 16 bits: map_point never clamps, so out-of-bounds
    release coordinates can be negative and must wrap as signed words."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def mouse_wparam_from_state(state: int) -> int:
    """X state mask -> MK_* wParam flags. Only the left button matters:
    the service injects button-1 gestures and unclicked hover motion;
    modifier MK flags are never set."""
    return MK_LBUTTON if state & _X_BUTTON1_MASK else 0

class Win32Backend:
    def __init__(self):
        pass

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_window_x(self, win_id_str: str) -> int | None:
        try:
            hwnd = int(win_id_str)
            rect = win32gui.GetWindowRect(hwnd)
            return rect[0]
        except Exception:
            return None

    def get_window_pid(self, win_id_str: str) -> int | None:
        try:
            hwnd = int(win_id_str)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid
        except Exception:
            return None

    def _get_vk(self, keysym_str: str):
        if keysym_str in WIN32_MODIFIER_OVERRIDES:
            return WIN32_MODIFIER_OVERRIDES[keysym_str][0]
        if keysym_str in VK_MAP:
            return VK_MAP[keysym_str]
        if len(keysym_str) == 1:
            try:
                vk = win32api.VkKeyScan(keysym_str) & 0xFF
                if vk != 0xFF:
                    return vk
            except Exception:
                pass
        return None

    def _send(self, win_id_str: str, msg: int, vk: int, keysym_str: str = "") -> bool:
        try:
            hwnd = int(win_id_str)
            if keysym_str in WIN32_MODIFIER_OVERRIDES:
                vk, scan_code, extended = WIN32_MODIFIER_OVERRIDES[keysym_str]
            else:
                scan_code = win32api.MapVirtualKey(vk, 0)
                extended = keysym_str in EXTENDED_KEYSYMS
            lparam = (scan_code << 16) | 1
            if extended:
                lparam |= (1 << 24)  # extended-key flag
            if msg == win32con.WM_KEYUP:
                lparam |= (1 << 30)
                lparam |= (1 << 31)
            win32gui.PostMessage(hwnd, msg, vk, lparam)
            return True
        except (ValueError, OSError) as e:
            print(f"[Win32Backend] PostMessage failed: {e}")
            return False

    def send_keydown(self, win_id_str: str, keysym_str: str, state: int = 0) -> bool:
        vk = self._get_vk(keysym_str)
        if not vk: return False
        return self._send(win_id_str, win32con.WM_KEYDOWN, vk, keysym_str)

    def send_keyup(self, win_id_str: str, keysym_str: str, state: int = 0) -> bool:
        vk = self._get_vk(keysym_str)
        if not vk: return False
        return self._send(win_id_str, win32con.WM_KEYUP, vk, keysym_str)

    def send_key(self, win_id_str: str, keysym_str: str, modifiers: list = None) -> bool:
        mod_map = {"shift": "Shift_L", "ctrl": "Control_L", "alt": "Alt_L"}
        mods_to_send = [mod_map[m.lower()] for m in (modifiers or []) if m.lower() in mod_map]

        success = True
        for mod in mods_to_send:
            if not self.send_keydown(win_id_str, mod, 0): success = False

        if not self.send_keydown(win_id_str, keysym_str, 0): success = False

        if not self.send_keyup(win_id_str, keysym_str, 0): success = False

        for mod in reversed(mods_to_send):
            if not self.send_keyup(win_id_str, mod, 0): success = False

        return success

    # ── mouse injection (click sync; PostMessage = background delivery,
    # never moves the real cursor; spike-verified against live TTR) ─────

    def _post_mouse(self, win_id_str: str, msg: int, wparam: int,
                    x: int, y: int) -> bool:
        try:
            hwnd = int(win_id_str)
            if not win32gui.IsWindow(hwnd):
                return False  # the XSendEvent BadWindow analogue
            win32gui.PostMessage(hwnd, msg, wparam, pack_mouse_lparam(x, y))
            return True
        except Exception:
            return False

    def send_button_press(self, win_id_str: str, x: int, y: int,
                          root_x: int, root_y: int, button: int = 1,
                          state: int = 0, time: int = 0) -> bool:
        # root_x/root_y/time accepted for XlibBackend signature parity;
        # PostMessage carries neither screen coords nor a timestamp.
        # WM_LBUTTONDOWN's wParam includes the button going down.
        return self._post_mouse(win_id_str, WM_LBUTTONDOWN, MK_LBUTTON, x, y)

    def send_button_release(self, win_id_str: str, x: int, y: int,
                            root_x: int, root_y: int, button: int = 1,
                            state: int = 0, time: int = 0) -> bool:
        # WM_LBUTTONUP's wParam excludes the button being released, so it
        # is 0 even for drains (which set Button1Mask in `state`).
        return self._post_mouse(win_id_str, WM_LBUTTONUP, 0, x, y)

    def send_motion(self, win_id_str: str, x: int, y: int,
                    root_x: int, root_y: int,
                    state: int = 0, time: int = 0) -> bool:
        return self._post_mouse(win_id_str, WM_MOUSEMOVE,
                                mouse_wparam_from_state(state), x, y)

    def sync(self):
        pass
