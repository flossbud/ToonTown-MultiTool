"""MacOSCarbonHotkeys provider: compile/register semantics + dispatch model
(offscreen; Carbon faked - the ctypes shell is exercised live, not here).

CP9 laws pinned: single-key+modifier chords register with Carbon masks
(super=cmdKey, alt=optionKey); two-key chords are recorded as failures
(RegisterEventHotKey cannot express them - HotkeyManager's tap-side fallback
owns them, scoped to capture); re-apply drops previous registrations; the
dispatch model fires once per physical press with repeat_ok re-fire parity.
"""
from __future__ import annotations

import sys

import pytest

from services.global_hotkeys import CARBON_MOD_MASKS, MacOSCarbonHotkeys


class _FakeCarbon:
    """Records RegisterEventHotKey/UnregisterEventHotKey traffic. hk_id is
    the ctypes structure passed by value; .id is readable directly."""

    def __init__(self, register_err=0):
        self.registered = []      # (vk, mods, hk_id.id)
        self.unregistered = []
        self.register_err = register_err

    def RegisterEventHotKey(self, vk, mods, hk_id, _target, _opts, _ref_out):
        err = (self.register_err(vk, mods)
               if callable(self.register_err) else self.register_err)
        if err == 0:
            self.registered.append((int(vk), int(mods), int(hk_id.id)))
        return err

    def UnregisterEventHotKey(self, ref):
        self.unregistered.append(ref)
        return 0


def _provider(fake=None, repeat_ok=frozenset()):
    p = MacOSCarbonHotkeys(repeat_ok_ids=repeat_ok)
    p._carbon = fake if fake is not None else _FakeCarbon()
    p._target = 1
    return p


def test_single_key_chords_register_with_carbon_masks():
    fake = _FakeCarbon()
    p = _provider(fake)
    p.apply_bindings({
        "a_ctrl1": "ctrl+1",
        "b_superh": "super+h",
        "c_altshiftf5": "alt+shift+F5",
        "d_baref6": "F6",
    })
    by_action = {p._id_to_action[i]: (vk, mods)
                 for vk, mods, i in fake.registered}
    assert by_action["a_ctrl1"] == (0x12, CARBON_MOD_MASKS["ctrl"])
    assert by_action["b_superh"] == (0x04, CARBON_MOD_MASKS["super"])
    assert by_action["c_altshiftf5"] == (
        0x60, CARBON_MOD_MASKS["alt"] | CARBON_MOD_MASKS["shift"])
    assert by_action["d_baref6"] == (0x61, 0)
    assert p.failures() == {}


def test_two_key_chord_is_a_recorded_failure_not_registered():
    fake = _FakeCarbon()
    p = _provider(fake)
    p.apply_bindings({"pair": "ctrl+1+2", "single": "ctrl+3"})
    assert [a for _v, _m, i in fake.registered
            for a in [p._id_to_action[i]]] == ["single"]
    assert "pair" in p.failures()
    assert "two-key" in p.failures()["pair"]


def test_unknown_keysym_and_garbage_chord_fail_soft():
    p = _provider()
    p.apply_bindings({"nokey": "ctrl+KP_Separator", "garbage": "+++"})
    assert set(p.failures()) == {"nokey", "garbage"}
    assert p._id_to_action == {}


def test_duplicate_chord_fails_second_action():
    p = _provider()
    p.apply_bindings({"aaa": "ctrl+1", "bbb": "ctrl+1"})
    assert list(p._id_to_action.values()) == ["aaa"]   # sorted order wins
    assert "duplicate of aaa" in p.failures()["bbb"]


def test_register_error_recorded_per_action():
    fake = _FakeCarbon(register_err=lambda vk, mods: -9878 if vk == 0x12 else 0)
    p = _provider(fake)
    p.apply_bindings({"bad": "ctrl+1", "good": "ctrl+2"})
    assert list(p._id_to_action.values()) == ["good"]
    assert "err=-9878" in p.failures()["bad"]


def test_reapply_unregisters_previous_registrations():
    fake = _FakeCarbon()
    p = _provider(fake)
    p.apply_bindings({"one": "ctrl+1", "two": "ctrl+2"})
    assert len(fake.registered) == 2 and fake.unregistered == []
    p.apply_bindings({"three": "ctrl+3"})
    assert len(fake.unregistered) == 2          # both old refs dropped
    assert list(p._id_to_action.values()) == ["three"]


def test_apply_without_start_is_inert():
    p = MacOSCarbonHotkeys()
    p.apply_bindings({"one": "ctrl+1"})         # _carbon is None
    assert p.failures() == {}


def test_start_refuses_off_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert MacOSCarbonHotkeys().start() is False


# ── dispatch model (pure; the ctypes shell feeds it live) ───────────────────

_PRESSED = 5
_RELEASED = 6


def test_dispatch_fires_once_per_physical_press():
    p = _provider()
    p.apply_bindings({"act": "ctrl+1"})
    seen = []
    p.action_triggered.connect(seen.append)
    hk_id = next(iter(p._id_to_action))
    p._dispatch(_PRESSED, hk_id)
    p._dispatch(_PRESSED, hk_id)                # OS auto-repeat: gated
    assert seen == ["act"]
    p._dispatch(_RELEASED, hk_id)
    p._dispatch(_PRESSED, hk_id)                # fresh physical press
    assert seen == ["act", "act"]


def test_dispatch_repeat_ok_action_refires_while_held():
    p = _provider(repeat_ok=frozenset({"rep"}))
    p.apply_bindings({"rep": "ctrl+1"})
    seen = []
    p.action_triggered.connect(seen.append)
    hk_id = next(iter(p._id_to_action))
    p._dispatch(_PRESSED, hk_id)
    p._dispatch(_PRESSED, hk_id)
    assert seen == ["rep", "rep"]


def test_dispatch_unknown_id_is_ignored():
    p = _provider()
    seen = []
    p.action_triggered.connect(seen.append)
    p._dispatch(_PRESSED, 99)
    assert seen == []


def test_stop_unregisters_and_drops_carbon():
    fake = _FakeCarbon()
    p = _provider(fake)
    p._handler_ref = object()

    removed = []
    fake.RemoveEventHandler = lambda ref: removed.append(ref)
    p.apply_bindings({"one": "ctrl+1"})
    p.stop()
    assert len(fake.unregistered) == 1
    assert len(removed) == 1
    assert p._carbon is None and p._id_to_action == {}
