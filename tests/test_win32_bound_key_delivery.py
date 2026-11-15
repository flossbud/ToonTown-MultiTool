"""Windows contract between the keyboard hook and the per-toon router.

On Windows the low-level hook WITHHOLDS every keymap-bound key from the
focused game window, on the promise that the router re-delivers it. Nothing
else delivers a withheld key there (focused passthrough is X11-only), so any
bound key the dispatcher does not send through the router is simply dead for
the focused toon. That is what happened to keys bound on Ctrl/Shift/Alt: the
chat gate classed them as plain modifiers, which broadcast the raw key to
background windows only.

These tests drive the real Win32MovementKeyGrabber, the real HotkeyManager
event filter and the real dispatcher together, so the two layers cannot
drift apart again unnoticed.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_win32_bound_key_delivery.py -v
"""
from __future__ import annotations

import queue
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from utils.win32_movement_grabber import _HOOK_VK_FOR_KEYSYM

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101


class _Suppressed(Exception):
    """Stands in for pynput's SuppressException."""


class _Rig:
    """Two TTR toons, the Windows grabber armed for the focused one."""

    def __init__(self, monkeypatch, tmp_path, *, setup, assignments, active):
        monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
        monkeypatch.delenv("TTMT_CHAT_FSM", raising=False)   # shipped default
        monkeypatch.setattr(
            "services.input_service.InputService._start_key_grabber",
            lambda self: None)
        monkeypatch.setattr(
            "services.input_service.InputService._apply_backend_setting",
            lambda self: None)
        monkeypatch.setattr(
            "utils.win32_movement_grabber.win32_grabber_available", lambda: True)
        registry = MagicMock()
        registry.get_game_for_window.side_effect = lambda wid: "ttr"
        monkeypatch.setattr(
            "utils.game_registry.GameRegistry.instance", lambda: registry)

        from services.hotkey_manager import HotkeyManager
        from services.input_service import InputService
        from utils.keymap_manager import KeymapManager
        from utils.win32_movement_grabber import Win32MovementKeyGrabber

        self.windows = ["t1", "t2"]
        self.active = active
        self.assignments = list(assignments)
        self.km = KeymapManager()
        setup(self.km)
        wm = SimpleNamespace(
            get_active_window=lambda: self.active,
            get_window_ids=lambda: list(self.windows),
            assign_windows=lambda: None,
            should_capture_input=lambda: True,
            active_window_changed=SimpleNamespace(connect=lambda *a, **k: None),
            active_window_id=active,
        )
        store = {}
        sm = SimpleNamespace(get=lambda k, d=None: store.get(k, d),
                             set=lambda k, v: store.__setitem__(k, v),
                             on_change=lambda cb: None)
        self.q: queue.Queue = queue.Queue()
        self.svc = InputService(
            window_manager=wm,
            get_enabled_toons=lambda: [True, True],
            get_movement_modes=lambda: ["x", "x"],
            get_event_queue_func=lambda: self.q,
            keymap_manager=self.km,
            get_keymap_assignments=lambda: list(self.assignments),
            settings_manager=sm,
        )
        assert self.svc._fsm_enabled is True
        self.svc._xlib = object()                 # a live delivery backend
        self.sent: list[tuple[str, str, str]] = []
        self.svc._send_via_backend = (
            lambda action, win, keysym, modifiers=None:
            self.sent.append((action, str(win), keysym)))

        grabber = Win32MovementKeyGrabber()
        assert grabber.prepare(
            should_consume=self.svc._should_consume_grabbed_key,
            on_grabs_changed=self.svc._on_grabs_changed)
        self.svc._key_grabber = grabber
        self.svc._on_active_window_changed_for_grabber(active)
        assert self.svc._strict_ttr_active() is True

        self.hk = HotkeyManager(
            wm, self.q,
            suppress_predicate=self.svc._suppress_predicate,
            vk_keysym_lookup=self.svc.grabber_keysym_for_vk)

        def _raise():
            raise _Suppressed()
        self.hk.listener = SimpleNamespace(suppress_event=_raise)

    def _hook(self, msg, key) -> bool:
        """Feed one physical event to the LL hook. True = withheld from the
        focused window."""
        try:
            self.hk._win32_event_filter(
                msg, SimpleNamespace(vkCode=_HOOK_VK_FOR_KEYSYM[key]))
        except _Suppressed:
            return True
        return False

    def _args(self):
        enabled = self.svc.get_enabled_toons()
        return (enabled, self.svc._get_assignments(enabled),
                self.svc._movement_keys())

    def press(self, key) -> list[tuple[str, str, str]]:
        """Physical keydown. Returns what the dispatcher delivered."""
        assert self._hook(WM_KEYDOWN, key), f"{key} should be withheld"
        assert self.q.get_nowait() == ("keydown", key)
        enabled, assignments, mk = self._args()
        before = len(self.sent)
        self.svc._fsm_handle_keydown(
            key, time.monotonic(), enabled, assignments, mk, self.windows)
        return self.sent[before:]

    def release(self, key) -> list[tuple[str, str, str]]:
        assert self._hook(WM_KEYUP, key), f"{key} release should be withheld"
        assert self.q.get_nowait() == ("keyup", key)
        enabled, assignments, mk = self._args()
        before = len(self.sent)
        self.svc._fsm_handle_keyup(key, time.monotonic(), enabled, assignments, mk)
        self.svc._dispatch_keyup(key, enabled, assignments)
        return self.sent[before:]


def _wasd(km, idx):
    for action, key in (("forward", "w"), ("reverse", "s"),
                        ("left", "a"), ("right", "d")):
        km.update_set_key("ttr", idx, action, key)


def _split_ctrl(km):
    """The requested setup: two sets, jump on L Ctrl and R Ctrl. Set 0 also
    stands for the client's own binding. 'control' is TTR's stock jump key
    (read from a fresh Windows install's settings.json), and TTMT imports
    it into the Default set as Control_L."""
    km.update_set_key("ttr", 0, "jump", "Control_L")
    km.add_set("ttr")
    _wasd(km, 1)
    km.update_set_key("ttr", 1, "jump", "Control_R")


def _space_default_ctrl_second(km):
    """Client jump stays on space; only the second set moves jump to R Ctrl."""
    km.add_set("ttr")
    _wasd(km, 1)
    km.update_set_key("ttr", 1, "jump", "Control_R")


def _same_ctrl_both(km):
    km.update_set_key("ttr", 0, "jump", "Control_L")
    km.add_set("ttr")
    _wasd(km, 1)
    km.update_set_key("ttr", 1, "jump", "Control_L")


def _stock_ctrl_and_space_second(km):
    """What was tried on a real Windows install: the Default set mirrors the
    stock client (jump = 'control', stored as Control_L); the second set
    moves jump to space."""
    km.update_set_key("ttr", 0, "jump", "Control_L")
    km.add_set("ttr")
    _wasd(km, 1)
    km.update_set_key("ttr", 1, "jump", "space")


@pytest.mark.parametrize("active", ["t1", "t2"])
class TestSplitJumpOnLeftAndRightCtrl:
    def test_left_ctrl_jumps_only_the_first_toon(self, monkeypatch, tmp_path, active):
        rig = _Rig(monkeypatch, tmp_path, setup=_split_ctrl,
                   assignments=[0, 1], active=active)
        assert rig.press("Control_L") == [("keydown", "t1", "Control_L")]
        assert rig.release("Control_L") == [("keyup", "t1", "Control_L")]

    def test_right_ctrl_jumps_only_the_second_toon(self, monkeypatch, tmp_path, active):
        """R Ctrl is the second toon's jump. Its client still binds jump to
        'control', so what it receives is the client's key, not the raw one."""
        rig = _Rig(monkeypatch, tmp_path, setup=_split_ctrl,
                   assignments=[0, 1], active=active)
        assert rig.press("Control_R") == [("keydown", "t2", "Control_L")]
        assert rig.release("Control_R") == [("keyup", "t2", "Control_L")]

    def test_space_client_binding_with_right_ctrl_second_set(self, monkeypatch, tmp_path, active):
        rig = _Rig(monkeypatch, tmp_path, setup=_space_default_ctrl_second,
                   assignments=[0, 1], active=active)
        assert rig.press("space") == [("keydown", "t1", "space")]
        rig.release("space")
        assert rig.press("Control_R") == [("keydown", "t2", "space")]
        assert rig.release("Control_R") == [("keyup", "t2", "space")]


@pytest.mark.parametrize("active", ["t1", "t2"])
def test_same_ctrl_key_in_two_sets_jumps_both(monkeypatch, tmp_path, active):
    """Different sets, jump on the same key: both toons jump, the focused
    one included (its key was withheld by the hook, so the router's send is
    its only delivery)."""
    rig = _Rig(monkeypatch, tmp_path, setup=_same_ctrl_both,
               assignments=[0, 1], active=active)
    assert sorted(rig.press("Control_L")) == [
        ("keydown", "t1", "Control_L"), ("keydown", "t2", "Control_L")]


@pytest.mark.parametrize("active", ["t1", "t2"])
def test_same_space_key_in_two_sets_jumps_both(monkeypatch, tmp_path, active):
    def setup(km):
        km.add_set("ttr")
        _wasd(km, 1)
    rig = _Rig(monkeypatch, tmp_path, setup=setup,
               assignments=[0, 1], active=active)
    assert sorted(rig.press("space")) == [
        ("keydown", "t1", "space"), ("keydown", "t2", "space")]


@pytest.mark.parametrize("setup", [_split_ctrl, _space_default_ctrl_second,
                                   _same_ctrl_both, _stock_ctrl_and_space_second])
@pytest.mark.parametrize("active", ["t1", "t2"])
def test_no_withheld_key_is_eaten(monkeypatch, tmp_path, setup, active):
    """THE contract. For every key the hook withholds, the dispatcher must
    deliver the client's binding to exactly the toons whose set binds that
    key, and that includes the focused toon. A key the focused toon's set
    binds that produces no send to the focused window is a dead key."""
    rig = _Rig(monkeypatch, tmp_path, setup=setup,
               assignments=[0, 1], active=active)
    withheld = sorted(rig.svc._key_grabber._grabbed_keysyms)
    assert {"Control_L", "Alt_L", "Shift_L"} <= set(withheld) or \
        {"Control_R", "Alt_L", "Shift_L"} <= set(withheld)
    for key in withheld:
        expected = set()
        for win, set_idx in zip(rig.windows, rig.assignments):
            action = rig.km.get_action_in_set("ttr", set_idx, key)
            if action is not None:
                expected.add(("keydown", win,
                              rig.km.get_key_for_action("ttr", 0, action)))
        got = rig.press(key)
        assert set(got) == expected, f"{key}: delivered {got}, wanted {expected}"
        assert len(got) == len(expected), f"{key}: duplicate sends {got}"
        ups = rig.release(key)
        assert {(w, k) for (_, w, k) in ups} == {(w, k) for (_, w, k) in got}, (
            f"{key}: release {ups} does not pair with press {got}")
    assert len(rig.svc.holds) == 0



@pytest.mark.parametrize("active", ["t1", "t2"])
class TestOtherSideOfAClientModifier:
    """TTR's `jump: control` fires for EITHER Ctrl key, but the Default set
    stores it as Control_L. Right Ctrl was therefore an unknown key: the hook
    let the focused window have it (the client jumped whatever set the toon
    was on) and the dispatcher broadcast it raw to every background window
    (those clients jumped too). Live symptom: toon 2 on a jump=space set
    jumped on Ctrl together with toon 1."""

    def test_right_ctrl_is_withheld_and_jumps_only_the_default_set_toon(
            self, monkeypatch, tmp_path, active):
        rig = _Rig(monkeypatch, tmp_path, setup=_stock_ctrl_and_space_second,
                   assignments=[0, 1], active=active)
        assert "Control_R" in rig.svc._key_grabber._grabbed_keysyms
        assert rig.press("Control_R") == [("keydown", "t1", "Control_L")]
        assert rig.release("Control_R") == [("keyup", "t1", "Control_L")]

    def test_left_ctrl_still_jumps_only_the_default_set_toon(
            self, monkeypatch, tmp_path, active):
        rig = _Rig(monkeypatch, tmp_path, setup=_stock_ctrl_and_space_second,
                   assignments=[0, 1], active=active)
        assert rig.press("Control_L") == [("keydown", "t1", "Control_L")]
        rig.release("Control_L")
        assert rig.press("space") == [("keydown", "t2", "Control_L")]

    def test_explicit_right_ctrl_binding_wins_over_the_alias(
            self, monkeypatch, tmp_path, active):
        """Once a set binds Right Ctrl itself, it stops standing in for the
        Default set's Ctrl: that is the split L/R setup."""
        rig = _Rig(monkeypatch, tmp_path, setup=_split_ctrl,
                   assignments=[0, 1], active=active)
        assert rig.press("Control_R") == [("keydown", "t2", "Control_L")]
