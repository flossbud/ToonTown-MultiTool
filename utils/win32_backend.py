"""
Win32-based input backend for ToonTown MultiTool.

Replaces Xlib calls with pywin32 (win32gui, win32api, win32process, win32con).
Uses PostMessage to send keystrokes to background windows without stealing focus.
"""

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    pass

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
    'Shift_L': win32con.VK_LSHIFT,
    'Shift_R': win32con.VK_RSHIFT,
    'Control_L': win32con.VK_LCONTROL,
    'Control_R': win32con.VK_RCONTROL,
    'Alt_L': win32con.VK_LMENU,
    'Alt_R': win32con.VK_RMENU,
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
# Map common Windows nokeysym pynput KeyCode char overrides to standardized strings
VK_TO_KEYSYM = {
    96: 'KP_0', 97: 'KP_1', 98: 'KP_2', 99: 'KP_3', 100: 'KP_4',
    101: 'KP_5', 102: 'KP_6', 103: 'KP_7', 104: 'KP_8', 105: 'KP_9',
    106: 'KP_Multiply', 107: 'KP_Add', 109: 'KP_Subtract', 110: 'KP_Decimal', 111: 'KP_Divide'
}

for c in 'abcdefghijklmnopqrstuvwxyz':
    VK_MAP[c] = ord(c.upper())

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
        
    def _send(self, win_id_str: str, msg: int, vk: int) -> bool:
        try:
            hwnd = int(win_id_str)
            scan_code = win32api.MapVirtualKey(vk, 0)
            lparam = (scan_code << 16) | 1
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
        return self._send(win_id_str, win32con.WM_KEYDOWN, vk)

    def send_keyup(self, win_id_str: str, keysym_str: str, state: int = 0) -> bool:
        vk = self._get_vk(keysym_str)
        if not vk: return False
        return self._send(win_id_str, win32con.WM_KEYUP, vk)

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

    def sync(self):
        pass
