"""HotkeyManager.normalize_key must produce TTMT's X-keysym strings for
nav cluster and F-key events from pynput. Without these mappings, the
foreground listener drops the user's keypress before it ever reaches the
InputService event queue, so e.g. pressing F8 to open the sticker book
forwards nothing to background toons even when set 1's 'book' field is
correctly bound to F8."""
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_hotkey_manager():
    """Construct a HotkeyManager with stub deps. We never start the listener."""
    from services.hotkey_manager import HotkeyManager
    wm = MagicMock()
    return HotkeyManager(wm, MagicMock())


def _named_key(name, vk=None):
    """Mimic the shape of a pynput keyboard.Key enum member."""
    obj = SimpleNamespace(name=name)
    if vk is not None:
        obj.vk = vk
    return obj


def test_normalize_home_key():
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("home")) == "Home"


def test_normalize_end_key():
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("end")) == "End"


def test_normalize_page_up_key():
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("page_up")) == "Prior"


def test_normalize_page_down_key():
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("page_down")) == "Next"


def test_normalize_insert_key():
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("insert")) == "Insert"


def test_normalize_f1_through_f12():
    hm = _make_hotkey_manager()
    for n in range(1, 13):
        assert hm.normalize_key(_named_key(f"f{n}")) == f"F{n}", (
            f"f{n} must normalize to F{n} (X keysym style) for keymap matching"
        )


def test_normalize_modifier_sides():
    """Left/right modifier events must normalize to side-specific canonicals,
    or a keymap bound to one side matches the wrong side (or nothing)."""
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("alt_l")) == "Alt_L"
    assert hm.normalize_key(_named_key("alt_r")) == "Alt_R"
    assert hm.normalize_key(_named_key("ctrl_l")) == "Control_L"
    assert hm.normalize_key(_named_key("ctrl_r")) == "Control_R"
    assert hm.normalize_key(_named_key("shift_l")) == "Shift_L"
    assert hm.normalize_key(_named_key("shift_r")) == "Shift_R"


def test_normalize_alt_gr_is_right_alt():
    # pynput's win32 backend resolves VK_RMENU (0xA5) to Key.alt_gr, not
    # Key.alt_r: both enum members share the vk and alt_gr is defined later,
    # so it wins the vk->Key dict. Every physical right-alt press on Windows
    # therefore arrives named "alt_gr"; without this mapping the press is
    # dropped before the event queue and Alt_R keymap bindings can never fire.
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_named_key("alt_gr")) == "Alt_R"


def test_win32_vk_fallback_maps_letters_and_digits(monkeypatch):
    # win32: Ctrl/Alt+letter suppresses the WM char translation so pynput
    # reports char=None; the VK code (ASCII for 0-9/A-Z) is all that's left.
    import sys
    monkeypatch.setattr(sys, "platform", "win32")
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_bare_vk_key(0x48)) == "h"   # VK 'H' -> lowercase
    assert hm.normalize_key(_bare_vk_key(0x41)) == "a"
    assert hm.normalize_key(_bare_vk_key(0x5A)) == "z"
    assert hm.normalize_key(_bare_vk_key(0x30)) == "0"
    assert hm.normalize_key(_bare_vk_key(0x39)) == "9"


def test_win32_vk_fallback_ignores_non_alnum_vks(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "win32")
    hm = _make_hotkey_manager()
    assert hm.normalize_key(_bare_vk_key(0x2F)) is None   # below '0'
    assert hm.normalize_key(_bare_vk_key(0x5B)) is None   # above 'Z' (VK_LWIN)


def test_vk_fallback_not_applied_off_win32(monkeypatch):
    # Linux keysyms already surface the char; darwin ANSI keycodes are
    # layout-relative, not ASCII -- the fallback must stay win32-only.
    import sys
    hm = _make_hotkey_manager()
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(sys, "platform", platform)
        assert hm.normalize_key(_bare_vk_key(0x48)) is None


def _bare_vk_key(vk):
    """A key with ONLY a vk (char=None, name=None), as win32 pynput reports
    letter/digit keys while Ctrl or Alt is held."""
    return SimpleNamespace(char=None, name=None, vk=vk)
