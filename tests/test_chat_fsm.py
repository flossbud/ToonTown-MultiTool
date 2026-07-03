"""Exhaustive offline tests for the parity-free chat gate FSM.

Pure module — no Qt, no threads, no real clock. Every rule here maps to a
line in docs/superpowers/plans/2026-07-03-chat-fsm-redesign.md; the
worst-case-bounds properties at the bottom are the design's contract:
no reachable state blocks a HELD bound key longer than T_DEMOTE, and no
reachable state defers a background tap longer than GRACE_DEFER.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_chat_fsm.py -v
"""
from __future__ import annotations

import random

import pytest

from services.chat_fsm import (
    ChatCtx,
    ChatFsm,
    ChatFsmConfig,
    ChatState,
    KeyClass,
)


WASD = frozenset({"w", "a", "s", "d", "space", "Alt_L", "g", "t", "Delete"})
WASD_ARROWS = WASD | frozenset({"Up", "Down", "Left", "Right", "Alt_R", "Shift_R"})

CFG = ChatFsmConfig()


def ctx(bound=WASD_ARROWS, mode_b=False, chords=None):
    if chords is None:
        return ChatCtx(bound_keys=bound, mode_b=mode_b)
    return ChatCtx(bound_keys=bound, mode_b=mode_b, open_chords=chords)


def tap(fsm, key, t, c, dur=0.05):
    """Press and release a key; returns (down_decision, up_result, t_after)."""
    d = fsm.on_keydown(key, t, c)
    u = fsm.on_keyup(key, t + dur, c)
    return d, u, t + dur


# ── Chord classification in ROUTE ────────────────────────────────────────────

class TestChordInRoute:
    def test_enter_with_no_context_opens(self):
        fsm, c = ChatFsm(), ctx()
        d = fsm.on_keydown("Return", 10.0, c)
        assert d.kind is KeyClass.CHORD_OPEN
        assert d.open_key == "Return"
        assert fsm.state is ChatState.CAPTURE
        assert d.transitions[0].cause == "chord_open"

    def test_enter_after_unbound_tap_is_send_never_open(self):
        """THE whisper fix: Enter following typing evidence cannot latch."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        tap(fsm, "k", 10.2, c)          # burst -> CAPTURE_SOFT
        assert fsm.state is ChatState.CAPTURE_SOFT
        d = fsm.on_keydown("Return", 10.5, c)
        assert d.kind is KeyClass.CHORD_CLOSE   # whisper send
        assert fsm.state is ChatState.GRACE

    def test_single_char_reply_send(self):
        """Reply 'y' + Enter: one tap is context (no burst needed)."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        assert fsm.state is ChatState.ROUTE      # one event: no burst yet
        d = fsm.on_keydown("Return", 10.4, c)
        assert d.kind is KeyClass.CHORD_SEND
        assert fsm.state is ChatState.ROUTE

    def test_hesitation_pause_still_sends(self):
        """Type a short reply, re-read for 10s, then Enter -> SEND (context
        is event-ended, bounded only by the generous capture TTL)."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        d = fsm.on_keydown("Return", 20.0, c)
        assert d.kind is KeyClass.CHORD_SEND

    def test_stale_context_expires_at_ttl(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        d = fsm.on_keydown("Return", 10.0 + CFG.capture_ttl + 1.0, c)
        assert d.kind is KeyClass.CHORD_OPEN

    def test_typing_rollover_held_unbound_char_is_context(self):
        """'k' still physically down when Enter arrives -> SEND."""
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("k", 10.0, c)             # no keyup yet
        d = fsm.on_keydown("Return", 10.05, c)
        assert d.kind is KeyClass.CHORD_SEND

    def test_bound_taps_are_not_context(self):
        """Tap-steering (w, a) then Enter must OPEN — bound taps carry zero
        class information."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "w", 10.0, c)
        tap(fsm, "a", 10.2, c)
        assert fsm.state is ChatState.ROUTE      # no false soft-capture
        d = fsm.on_keydown("Return", 10.5, c)
        assert d.kind is KeyClass.CHORD_OPEN

    def test_group_chat_chord_alt_enter(self):
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Alt_L", 9.9, c)
        d = fsm.on_keydown("Return", 10.0, c)
        assert d.kind is KeyClass.CHORD_OPEN

    def test_bound_chord_key_is_movement_in_route(self):
        """Residual 8: binding the open-chord key disables chat capture."""
        c = ctx(bound=WASD_ARROWS | {"Return"})
        fsm = ChatFsm()
        d = fsm.on_keydown("Return", 10.0, c)
        assert d.kind is KeyClass.MOVEMENT
        assert fsm.state is ChatState.ROUTE

    def test_send_consumes_context_next_enter_opens(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        d1 = fsm.on_keydown("Return", 10.3, c)
        fsm.on_keyup("Return", 10.35, c)
        assert d1.kind is KeyClass.CHORD_SEND
        d2 = fsm.on_keydown("Return", 11.0, c)
        assert d2.kind is KeyClass.CHORD_OPEN

    def test_custom_rebound_chord(self):
        """Chord set follows the client's own config (e.g. chat rebound)."""
        chords = ((frozenset(), "F8"),)
        fsm, c = ChatFsm(), ctx(chords=chords)
        d = fsm.on_keydown("F8", 10.0, c)
        assert d.kind is KeyClass.CHORD_OPEN
        d2 = fsm.on_keydown("Return", 10.5, c)   # Return is not a chord now
        assert d2.kind is not KeyClass.CHORD_CLOSE

    def test_escape_unbound_clears_context_terminal(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        d = fsm.on_keydown("Escape", 10.3, c)
        assert d.kind is KeyClass.ESCAPE_CLEAR
        d2 = fsm.on_keydown("Return", 10.6, c)
        assert d2.kind is KeyClass.CHORD_OPEN    # context was cleared

    def test_escape_bound_routes_as_movement_in_route(self):
        """CC book=Escape keeps working during play."""
        c = ctx(bound=WASD | {"Escape"})
        fsm = ChatFsm()
        d = fsm.on_keydown("Escape", 10.0, c)
        assert d.kind is KeyClass.MOVEMENT


# ── CAPTURE behavior ─────────────────────────────────────────────────────────

class TestCapture:
    def _open(self, fsm, c, t=10.0):
        assert fsm.on_keydown("Return", t, c).kind is KeyClass.CHORD_OPEN
        fsm.on_keyup("Return", t + 0.05, c)
        return t + 0.1

    def test_enter_closes_after_typing(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        tap(fsm, "h", t, c)
        d = fsm.on_keydown("Return", t + 0.5, c)
        assert d.kind is KeyClass.CHORD_CLOSE
        assert d.transitions[0].cause == "send"
        assert fsm.state is ChatState.GRACE

    def test_enter_close_empty(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        d = fsm.on_keydown("Return", t, c)
        assert d.kind is KeyClass.CHORD_CLOSE
        assert d.transitions[0].cause == "close_empty"

    def test_escape_closes(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        d = fsm.on_keydown("Escape", t, c)
        assert d.kind is KeyClass.CHORD_CLOSE
        assert d.transitions[0].cause == "escape"

    def test_bound_escape_still_closes_during_capture(self):
        """State-dependent branch precedence: the 45131ce class cannot
        strand a capture (CC-foreground Escape-close now works)."""
        c = ctx(bound=WASD | {"Escape"})
        fsm = ChatFsm()
        t = self._open(fsm, c)
        d = fsm.on_keydown("Escape", t, c)
        assert d.kind is KeyClass.CHORD_CLOSE

    def test_bound_chord_key_still_closes_during_capture(self):
        c = ctx(bound=WASD | {"Return"})
        fsm = ChatFsm()
        # Force a capture through Mode B so we can test the close side.
        c_mb = ctx(bound=WASD | {"Return"}, mode_b=True)
        fsm.on_keydown("x", 10.0, c_mb)
        assert fsm.state is ChatState.CAPTURE
        d = fsm.on_keydown("Return", 10.5, c)
        assert d.kind is KeyClass.CHORD_CLOSE

    def test_typed_chars_are_typing_class(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        assert fsm.on_keydown("h", t, c).kind is KeyClass.TYPING
        assert fsm.on_keydown("w", t + 0.1, c).kind is KeyClass.TYPING  # bound: mirrored, never movement

    def test_backspace_is_edit(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        assert fsm.on_keydown("BackSpace", t, c).kind is KeyClass.EDIT

    def test_chat_edit_key_is_typing_and_refreshes_ttl(self):
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        base = t + CFG.capture_ttl - 1.0
        fsm.on_keydown("Left", base, c)          # cursor editing, bound or not
        fsm.on_keyup("Left", base + 0.05, c)
        r = fsm.on_tick(base + 2.0, c)           # would have expired without refresh
        assert fsm.state is ChatState.CAPTURE
        assert r.transitions == ()

    def test_bound_action_tap_demotes_immediately(self):
        c = ctx(bound=WASD_ARROWS | {"F3"})
        fsm = ChatFsm()
        t = self._open(fsm, c)
        d = fsm.on_keydown("F3", t, c)
        assert d.transitions[0].cause == "demote_tap"
        assert d.kind is KeyClass.MOVEMENT       # routed under the new state
        assert fsm.state is ChatState.GRACE

    def test_space_typed_in_chat_never_demotes(self):
        """The spacebar hole: space is bound (jump) by default AND typed at
        every word boundary — it must mirror as typing, not demote."""
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        d = fsm.on_keydown("space", t, c)
        assert d.kind is KeyClass.TYPING
        assert fsm.state is ChatState.CAPTURE

    def test_space_held_past_t_demote_still_demotes(self):
        """Residual 3's recorded tunable: a long HELD space is gameplay."""
        fsm, c = ChatFsm(), ctx()
        t = self._open(fsm, c)
        fsm.on_keydown("space", t, c)
        r = fsm.on_tick(t + CFG.t_demote + 0.05, c)
        assert r.transitions and r.transitions[0].cause == "demote_hold"


# ── Burst / CAPTURE_SOFT ─────────────────────────────────────────────────────

class TestBurst:
    def test_two_unbound_taps_within_window(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        _, u, _ = tap(fsm, "k", 10.4, c)
        assert fsm.state is ChatState.CAPTURE_SOFT
        assert u.transitions[0].cause == "burst"

    def test_taps_outside_window_do_not_burst(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        tap(fsm, "k", 10.0 + CFG.burst_window + 0.2, c)
        assert fsm.state is ChatState.ROUTE

    def test_tap_plus_backspace_bursts(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        fsm.on_keydown("BackSpace", 10.3, c)
        assert fsm.state is ChatState.CAPTURE_SOFT

    def test_soft_capture_suppresses_everything(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        tap(fsm, "k", 10.2, c)
        assert fsm.on_keydown("h", 10.4, c).kind is KeyClass.SUPPRESS
        assert fsm.on_keydown("w", 10.5, c).kind is KeyClass.SUPPRESS
        assert fsm.on_keydown("BackSpace", 10.6, c).kind is KeyClass.SUPPRESS

    def test_soft_capture_enter_is_send(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        tap(fsm, "k", 10.2, c)
        d = fsm.on_keydown("Return", 10.5, c)
        assert d.kind is KeyClass.CHORD_CLOSE
        assert d.transitions[0].cause == "send"

    def test_long_press_of_unbound_key_is_not_a_tap(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c, dur=CFG.tap_max + 0.1)
        tap(fsm, "k", 10.6, c, dur=CFG.tap_max + 0.1)
        assert fsm.state is ChatState.ROUTE


class TestModeB:
    def test_first_unbound_letter_opens_capture(self):
        fsm, c = ChatFsm(), ctx(mode_b=True)
        d = fsm.on_keydown("h", 10.0, c)
        assert d.kind is KeyClass.CHORD_OPEN
        assert d.open_key == "h"
        assert d.transitions[0].cause == "mode_b_letter"
        assert fsm.state is ChatState.CAPTURE

    def test_bound_first_letter_stays_route(self):
        """Residual 6: the game opens chat but the FSM cannot know yet."""
        fsm, c = ChatFsm(), ctx(mode_b=True)
        assert fsm.on_keydown("w", 10.0, c).kind is KeyClass.MOVEMENT
        assert fsm.state is ChatState.ROUTE

    def test_mode_b_enter_after_letters_closes(self):
        fsm, c = ChatFsm(), ctx(mode_b=True)
        fsm.on_keydown("h", 10.0, c)
        fsm.on_keyup("h", 10.05, c)
        d = fsm.on_keydown("Return", 10.5, c)
        assert d.kind is KeyClass.CHORD_CLOSE


# ── Demotion (gameplay evidence) ─────────────────────────────────────────────

class TestDemotion:
    def _soft(self, fsm, c, t=10.0):
        tap(fsm, "o", t, c)
        tap(fsm, "k", t + 0.2, c)
        assert fsm.state is ChatState.CAPTURE_SOFT
        return t + 0.4

    def test_bound_hold_demotes(self):
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("w", t, c)
        r = fsm.on_tick(t + CFG.t_demote + 0.05, c)
        assert r.transitions[0].cause == "demote_hold"
        assert fsm.state is ChatState.GRACE

    def test_bound_hold_under_threshold_does_not_demote(self):
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("w", t, c)
        r = fsm.on_tick(t + CFG.t_demote - 0.1, c)
        assert r.transitions == ()
        assert fsm.state is ChatState.CAPTURE_SOFT

    def test_single_arrow_hold_never_demotes(self):
        """Arrow = chat cursor editing, even when bound."""
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("Left", t, c)
        r = fsm.on_tick(t + 3.0, c)
        assert all(tr.cause != "demote_hold" for tr in r.transitions)

    def test_two_concurrent_arrows_demote(self):
        """Diagonal movement is not editing."""
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("Left", t, c)
        fsm.on_keydown("Up", t + 0.05, c)
        r = fsm.on_tick(t + 0.05 + CFG.chord_min_hold + CFG.chord_overlap, c)
        assert r.transitions and r.transitions[0].cause == "demote_chord"

    def test_two_concurrent_bound_keys_demote(self):
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("w", t, c)
        fsm.on_keydown("a", t + 0.05, c)
        r = fsm.on_tick(t + 0.45, c)
        assert r.transitions and r.transitions[0].cause == "demote_chord"

    def test_typing_rollover_does_not_demote(self):
        """Brief overlap of two bound letters (rollover typing) is safe."""
        fsm, c = ChatFsm(), ctx()
        t = self._soft(fsm, c)
        fsm.on_keydown("w", t, c)
        fsm.on_keydown("a", t + 0.1, c)
        fsm.on_keyup("w", t + 0.18, c)           # released before chord_min_hold
        r = fsm.on_tick(t + 0.3, c)
        assert fsm.state is ChatState.CAPTURE_SOFT
        assert r.transitions == ()

    def test_held_shift_never_demotes(self):
        """Shifted typing: modifiers are not gameplay evidence."""
        c = ctx(bound=WASD | {"Shift_L"})        # Shift bound to an action
        fsm = ChatFsm()
        tap(fsm, "o", 10.0, c)
        tap(fsm, "k", 10.2, c)
        fsm.on_keydown("Shift_L", 10.4, c)
        r = fsm.on_tick(12.0, c)
        assert fsm.state is ChatState.CAPTURE_SOFT
        assert r.transitions == ()


# ── TTL ──────────────────────────────────────────────────────────────────────

class TestTtl:
    def test_hands_off_ttl_fires(self):
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        fsm.on_keyup("Return", 10.05, c)
        r = fsm.on_tick(10.0 + CFG.capture_ttl + 0.5, c)
        assert r.transitions[0].cause == "ttl"
        assert fsm.state is ChatState.GRACE

    def test_movement_taps_do_not_refresh_ttl(self):
        """THE legacy defeat: mashing movement keys must not postpone the
        backstop."""
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        fsm.on_keyup("Return", 10.05, c)
        t = 10.0
        while t < 10.0 + CFG.capture_ttl:
            t += 1.0
            tap(fsm, "w", t, c, dur=0.1)         # frantic tapping
            fsm.on_tick(t + 0.2, c)
        r = fsm.on_tick(10.0 + CFG.capture_ttl + 0.5, c)
        causes = [tr.cause for tr in r.transitions]
        assert fsm.state is not ChatState.CAPTURE
        assert "ttl" in causes or fsm.state is ChatState.GRACE

    def test_unbound_typing_refreshes_ttl(self):
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        fsm.on_keyup("Return", 10.05, c)
        t_type = 10.0 + CFG.capture_ttl - 1.0
        tap(fsm, "h", t_type, c)
        r = fsm.on_tick(10.0 + CFG.capture_ttl + 5.0, c)   # < t_type + TTL
        assert fsm.state is ChatState.CAPTURE
        assert r.transitions == ()


# ── GRACE ────────────────────────────────────────────────────────────────────

class TestGrace:
    def _grace(self, fsm, c, t=10.0):
        fsm.on_keydown("Return", t, c)
        fsm.on_keyup("Return", t + 0.05, c)
        fsm.on_keydown("Escape", t + 0.2, c)
        fsm.on_keyup("Escape", t + 0.25, c)
        assert fsm.state is ChatState.GRACE
        return t + 0.3

    def test_grace_expires_to_route(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        r = fsm.on_tick(t + CFG.grace_s + 0.1, c)
        assert r.transitions[-1].cause == "grace_end"
        assert fsm.state is ChatState.ROUTE

    def test_bound_printable_tap_deferred_and_dropped(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        d = fsm.on_keydown("w", t, c)
        assert d.kind is KeyClass.DEFER_BG_TAP
        u = fsm.on_keyup("w", t + 0.1, c)        # released early: was typing
        assert u.dropped_defer == "w"

    def test_bound_printable_hold_confirmed(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        d = fsm.on_keydown("w", t, c)
        assert d.kind is KeyClass.DEFER_BG_TAP
        r = fsm.on_tick(t + CFG.grace_defer + 0.02, c)
        assert r.confirmed_defers == ("w",)      # deliver late keydown, acquire hold

    def test_bound_nonprintable_routes_instantly(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        assert fsm.on_keydown("Up", t, c).kind is KeyClass.MOVEMENT

    def test_burst_in_grace_reenters_soft_and_drops_defers(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        fsm.on_keydown("w", t, c)                # deferred
        tap(fsm, "o", t + 0.1, c)
        _, u, _ = tap(fsm, "k", t + 0.3, c)
        assert fsm.state is ChatState.CAPTURE_SOFT
        r = fsm.on_tick(t + 5.0, c)
        assert r.confirmed_defers == ()          # defer was cleared, not confirmed

    def test_enter_in_grace_opens_fresh(self):
        fsm, c = ChatFsm(), ctx()
        t = self._grace(fsm, c)
        d = fsm.on_keydown("Return", t + 0.2, c)
        assert d.kind is KeyClass.CHORD_OPEN
        assert fsm.state is ChatState.CAPTURE


# ── force_route / focus change / lifecycle ───────────────────────────────────

class TestLifecycle:
    def test_force_route_from_capture(self):
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        tr = fsm.force_route(11.0)
        assert tr[0].cause == "force"
        assert fsm.state is ChatState.ROUTE

    def test_force_route_idempotent_and_cheap(self):
        fsm = ChatFsm()
        assert fsm.force_route(10.0) == ()
        assert fsm.force_route(10.01) == ()

    def test_focus_switch_mid_capture_goes_grace(self):
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        tr = fsm.on_focus_change_managed(10.5)
        assert tr[0].cause == "focus_switch"
        assert fsm.state is ChatState.GRACE

    def test_focus_switch_in_route_is_noop(self):
        fsm = ChatFsm()
        assert fsm.on_focus_change_managed(10.0) == ()

    def test_force_route_clears_stale_context(self):
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)
        fsm.force_route(10.5)
        d = fsm.on_keydown("Return", 10.6, c)
        assert d.kind is KeyClass.CHORD_OPEN     # context did not survive


# ── ROUTE context contradiction ──────────────────────────────────────────────

class TestContextContradiction:
    def test_walking_clears_lingering_context(self):
        """A stray unbound tap must not make a chord much later misread as
        SEND once real play (a hold) happened in between."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "y", 10.0, c)                   # stray context
        fsm.on_keydown("w", 11.0, c)             # walk
        fsm.on_tick(11.0 + CFG.t_demote + 0.1, c)
        fsm.on_keyup("w", 13.0, c)
        d = fsm.on_keydown("Return", 13.5, c)
        assert d.kind is KeyClass.CHORD_OPEN


# ── Robustness / contract properties ─────────────────────────────────────────

class TestRobustness:
    def test_orphan_keyup_is_noop(self):
        """queue.Full can drop a keydown; its keyup must not crash or
        transition."""
        fsm, c = ChatFsm(), ctx()
        u = fsm.on_keyup("k", 10.0, c)
        assert u.transitions == () and u.dropped_defer is None

    def test_keydown_without_keyup_heals_via_ttl(self):
        """queue.Full can drop a keyup: a stuck-down unbound printable keeps
        rollover context alive, but a capture still exits via TTL."""
        fsm, c = ChatFsm(), ctx()
        tap(fsm, "o", 10.0, c)
        fsm.on_keydown("k", 10.2, c)             # keyup lost -> SOFT via down? no: evidence on up
        tap(fsm, "j", 10.3, c)                   # burst
        assert fsm.state is ChatState.CAPTURE_SOFT
        r = fsm.on_tick(10.3 + CFG.capture_ttl + 1.0, c)
        assert fsm.state is ChatState.GRACE
        assert r.transitions[0].cause == "ttl"

    def test_no_state_blocks_a_held_bound_key_past_t_demote(self):
        """Contract property: from ANY reachable state, a bound non-edit key
        held for T_DEMOTE (plus one tick) has exited capture."""
        rng = random.Random(42)
        keys = ["w", "a", "o", "k", "Return", "Escape", "BackSpace", "Left",
                "Up", "h", "space", "Shift_L"]
        for trial in range(60):
            fsm, c = ChatFsm(), ctx()
            t = 10.0
            for _ in range(rng.randint(1, 40)):
                k = rng.choice(keys)
                t += rng.random() * 0.4
                if rng.random() < 0.5:
                    fsm.on_keydown(k, t, c)
                else:
                    fsm.on_keyup(k, t + rng.random() * 0.3, c)
                if rng.random() < 0.3:
                    fsm.on_tick(t + 0.005, c)
            # Now the user HOLDS a bound movement key.
            t += 1.0
            fsm.on_keydown("s", t, c)
            fsm.on_tick(t + CFG.t_demote + 0.05, c)
            assert not fsm.in_capture, f"trial {trial}: stuck in {fsm.state}"

    def test_no_defer_outlives_grace_defer(self):
        """Contract property: a deferred bg tap is resolved (confirmed or
        dropped) within GRACE_DEFER of its keydown."""
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)
        fsm.on_keydown("Escape", 10.2, c)        # -> GRACE
        fsm.on_keydown("w", 10.4, c)
        r = fsm.on_tick(10.4 + CFG.grace_defer + 0.01, c)
        assert r.confirmed_defers == ("w",)

    def test_late_flushed_keyups_after_send_do_not_recapture(self):
        """Keyups buffered by the autorepeat dedup can flush AFTER the
        send-Enter processes. Their taps belong to the SENT message: they
        must not form a fresh burst into a capture nobody will close."""
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("o", 10.00, c)
        fsm.on_keydown("k", 10.10, c)            # rollover: both still down
        d = fsm.on_keydown("Return", 10.15, c)
        assert d.kind is KeyClass.CHORD_SEND     # held unbound chars = context
        fsm.on_keyup("o", 10.16, c)              # late flush, tap-shaped
        fsm.on_keyup("k", 10.17, c)
        assert fsm.state is ChatState.ROUTE      # no phantom re-capture
        # Fresh typing AFTER the send still counts normally.
        tap(fsm, "h", 11.0, c)
        tap(fsm, "i", 11.2, c)
        assert fsm.state is ChatState.CAPTURE_SOFT

    def test_duplicate_chord_events_do_not_invert_forever(self):
        """No parity: a spurious extra Enter costs at most one bounded wrong
        capture, healed by the next hold."""
        fsm, c = ChatFsm(), ctx()
        fsm.on_keydown("Return", 10.0, c)        # OPEN (maybe spurious)
        fsm.on_keyup("Return", 10.05, c)
        fsm.on_keydown("w", 11.0, c)             # user just plays
        fsm.on_tick(11.0 + CFG.t_demote + 0.05, c)
        assert not fsm.in_capture
