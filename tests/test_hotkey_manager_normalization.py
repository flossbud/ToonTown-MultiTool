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
