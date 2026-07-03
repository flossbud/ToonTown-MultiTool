"""Parity-free chat gate FSM.

Why: the legacy chat blocker inferred "chat box open on the focused toon"
from a blind Return toggle plus a per_toon-gated whisper detector. Any
open/close the keyboard stream cannot see (whisper click, chat button,
game-consumed Enter, alt-tab force-clear) inverted the belief until Escape,
a 15s idle timeout that movement keypresses kept postponing, or an F5
service restart. See docs/superpowers/plans/2026-07-03-chat-fsm-redesign.md
for the full design, review findings, and the accepted residuals.

This module is deliberately PURE: no Qt, no threads, no clocks of its own.
Every call takes `now` (the caller's monotonic timestamp; keyups should be
fed the pending_keyups buffered_at time, not flush time). The InputService
run loop feeds it key events and executes the returned decisions and
transitions through the existing side-effect helpers.

Core rules (each one exists to break a specific legacy failure):

- A chat chord is NEVER a toggle. From ROUTE it classifies against the
  composition context: typing evidence present -> SEND (never opens);
  absent -> OPEN. Inside a capture the chord always closes. A whisper
  reply's send-Enter therefore cannot latch the block on.
- Typing evidence comes ONLY from unbound keys (plus BackSpace, and
  chat-edit keys inside a capture). A sub-TAP_MAX tap of a bound key is
  byte-identical whether the user is typing or tap-steering, so bound keys
  carry zero class information and must not create false captures in play.
- Wrong captures are demolished by gameplay evidence that is physically
  impossible as chat typing: a bound non-modifier non-edit key held past
  T_DEMOTE, two concurrent bound holds, or a bound non-printable action
  tap. Escape-mashing a stuck state heals it instead of feeding it.
- The capture TTL is refreshed ONLY by chat-consistent evidence. Movement
  never refreshes it, so the hands-off backstop actually fires.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class ChatState(Enum):
    ROUTE = auto()          # chat closed; full movement routing
    CAPTURE = auto()        # chat open via explicit signal (chord OPEN / Mode B letter)
    CAPTURE_SOFT = auto()   # typing detected with no observed open (mouse-opened box)
    GRACE = auto()          # short post-capture cooldown; grabs reinstalled


class KeyClass(Enum):
    """What the dispatcher should do with the key event just classified."""
    MOVEMENT = auto()       # today's is_movement routing path
    MODIFIER = auto()       # today's modifier path
    TYPING = auto()         # typing path (_send_typing_to_bg with its filters)
    SUPPRESS = auto()       # deliver to no background toon (focused native/passthrough)
    EDIT = auto()           # BackSpace branch (per-state scope decided by dispatcher)
    ACTION = auto()         # today's unbound non-printable ACTION-hold branch
    CHORD_OPEN = auto()     # chat opened; mirror open_key to recipients, enter CAPTURE
    CHORD_SEND = auto()     # chord consumed as send in ROUTE/GRACE; focused passthrough only
    CHORD_CLOSE = auto()    # capture closed by chord/Escape; mirror close to bg_chat_open
    ESCAPE_CLEAR = auto()   # unbound Escape outside capture: terminal, focused passthrough only


@dataclass(frozen=True)
class Transition:
    old: "ChatState"
    new: "ChatState"
    cause: str  # chord_open | mode_b_letter | burst | send | close_empty | escape
    #             demote_hold | demote_chord | demote_tap | ttl | grace_end
    #             focus_switch | force


@dataclass(frozen=True)
class KeyDecision:
    kind: KeyClass
    transitions: tuple[Transition, ...] = ()
    open_key: Optional[str] = None   # key to mirror on CHORD_OPEN (chord key or Mode B letter)


@dataclass(frozen=True)
class UpResult:
    transitions: tuple[Transition, ...] = ()


@dataclass(frozen=True)
class TickResult:
    transitions: tuple[Transition, ...] = ()


@dataclass(frozen=True)
class ChatCtx:
    """Per-event context resolved by the caller (liveness by design, matching
    how the legacy dispatcher re-resolves settings per keystroke)."""
    bound_keys: frozenset                            # foreground game's all-sets union
    open_chords: tuple = (
        (frozenset(), "Return"),
        (frozenset({"alt"}), "Return"),
    )
    mode_b: bool = False                             # TTR chat-by-typing resolved on


@dataclass(frozen=True)
class ChatFsmConfig:
    """All tunables in one place. Live-tuned constants must be recorded in
    HANDOFF with a DISPROVEN entry for any rule they replace."""
    tap_max: float = 0.25        # max down->up for a "tap" (typing-shaped press)
    t_demote: float = 0.75       # bound non-modifier non-edit hold that proves play
    chord_overlap: float = 0.15  # concurrent-hold overlap that proves play
    chord_min_hold: float = 0.25 # each concurrent-hold member must be held this long
    burst_n: int = 2             # typing-evidence events ...
    burst_window: float = 1.0    # ... within this window => CAPTURE_SOFT
    grace_s: float = 1.5         # post-capture cooldown (bookkeeping only; routing
    #                              is fully live in GRACE — see DISPROVEN note below)
    capture_ttl: float = 15.0    # hands-off backstop; also composition-context expiry


# DISPROVEN (live Fedora validation, 2026-07-03): GRACE tap-deferral — bound
# printable taps hold-confirmed for GRACE_DEFER=200ms during the post-close
# window — as trailing-chat protection. With both toons on the Default
# (WASD) set it made background movement visibly sluggish for the whole
# GRACE window after EVERY sent message (late keydowns, dropped taps), while
# the leak it guarded against (letters typed after a send routing as one bg
# tap each) was never protected by the legacy system, was never reported,
# and was never covered on the whisper-send path anyway. Removed: bound keys
# route instantly in GRACE; continued typing is still caught by the burst
# detector; a stray trailing letter costs one bg tap (accepted residual
# class 1 in the plan).


# Keys that are legitimate chat-box editing: they never demote alone and they
# refresh the capture TTL even when bound (arrows are in the union whenever
# any keyset is "arrows"). Two CONCURRENT arrows still demote via the
# concurrent-hold rule: diagonal movement is not editing.
CHAT_EDIT_KEYS = frozenset({"Left", "Right", "Up", "Down", "Home", "End", "Delete"})

MODIFIER_KEYS = frozenset({
    "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Super_L", "Super_R", "Meta_L", "Meta_R",
})

_MOD_NAME = {
    "Shift_L": "shift", "Shift_R": "shift",
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt",
    "Super_L": "super", "Super_R": "super",
    "Meta_L": "meta", "Meta_R": "meta",
}


def _is_printable_char(key: str) -> bool:
    return len(key) == 1 and key.isprintable()


# Multi-char keysyms that ARE typed as chat content. space is bound (jump)
# by default AND appears at every word boundary of a real message, so it
# must never be read as a chat-impossible action tap (the review-flagged
# "spacebar hole"). A HELD space still demotes via the hold rule — that is
# the recorded tunable in the plan's residual 3.
_TYPEABLE_MULTICHAR = frozenset({"space"})


def _is_typeable(key: str) -> bool:
    return _is_printable_char(key) or key in _TYPEABLE_MULTICHAR


class ChatFsm:
    def __init__(self, config: Optional[ChatFsmConfig] = None) -> None:
        self.config = config or ChatFsmConfig()
        self._state = ChatState.ROUTE
        self._state_entered = 0.0
        # Physical tracking. _down holds every non-modifier key currently
        # down (bound or not) so tap/hold classification works uniformly;
        # modifiers are tracked by family name for chord matching.
        self._down: dict = {}
        self._mods_down: dict = {}
        # Unbound printables currently physically down: typing-rollover
        # evidence (a held unbound printable is typing; nobody holds a key
        # that does nothing in game).
        self._unbound_printable_down: set = set()
        # Composition context: evidence that the user is typing chat content.
        self._context_active = False
        self._context_last = 0.0
        self._typing_events: deque = deque()
        # Capture TTL bookkeeping (chat-consistent evidence only).
        self._last_chat_evidence = 0.0
        # Close-empty detection: was anything typed since the chord OPEN?
        self._open_had_typing = False
        # A chord verdict ENDS the composition: taps that STARTED before it
        # belong to the sent/closed message, so their (possibly buffered,
        # late-flushed) keyups must not count as fresh typing evidence and
        # re-trigger a burst with no close ever coming.
        self._last_chord_at = float("-inf")

    # ── public state ─────────────────────────────────────────────────────

    @property
    def state(self) -> ChatState:
        return self._state

    @property
    def in_capture(self) -> bool:
        return self._state in (ChatState.CAPTURE, ChatState.CAPTURE_SOFT)

    def context_active(self, now: float) -> bool:
        """Composition context, with lazy expiry. The expiry bound is the
        generous capture TTL: a typed-reply-then-long-pause still classifies
        the send chord as SEND (the hesitation case), while a stray tap
        cannot make a chord MINUTES later misread as SEND (bounded
        staleness). A held unbound printable counts as live evidence
        (typing rollover: 1-char reply still physically down at Enter)."""
        if self._context_active and now - self._context_last > self.config.capture_ttl:
            self._context_active = False
        return self._context_active or bool(self._unbound_printable_down)

    # ── events ───────────────────────────────────────────────────────────

    def on_keydown(self, key: str, now: float, ctx: ChatCtx) -> KeyDecision:
        if key in MODIFIER_KEYS:
            name = _MOD_NAME.get(key)
            if name:
                self._mods_down[name] = self._mods_down.get(name, 0) + 1
            return KeyDecision(KeyClass.MODIFIER)

        self._down[key] = now
        is_bound = key in ctx.bound_keys
        if not is_bound and _is_printable_char(key):
            self._unbound_printable_down.add(key)

        is_chord = self._matches_chord(key, ctx)

        if self.in_capture:
            return self._keydown_in_capture(key, now, ctx, is_bound, is_chord)
        return self._keydown_route_or_grace(key, now, ctx, is_bound, is_chord)

    def _keydown_in_capture(self, key, now, ctx, is_bound, is_chord) -> KeyDecision:
        # State-dependent branch precedence: chord/Escape/BackSpace outrank
        # movement classification while a capture is live, so a bound Escape
        # (CC book) or a bound chord key can still CLOSE a stuck capture —
        # the direction of the 45131ce shadowing bug that hurt.
        if is_chord:
            self._last_chord_at = now
            cause = "send"
            if self._state is ChatState.CAPTURE and not self._open_had_typing:
                cause = "close_empty"
            return KeyDecision(KeyClass.CHORD_CLOSE, self._go(ChatState.GRACE, cause, now))
        if key == "Escape":
            self._last_chord_at = now
            return KeyDecision(KeyClass.CHORD_CLOSE, self._go(ChatState.GRACE, "escape", now))
        if key == "BackSpace":
            trs = self._note_typing_evidence(now)
            self._open_had_typing = True
            if self._state is ChatState.CAPTURE_SOFT:
                return KeyDecision(KeyClass.SUPPRESS, trs)
            return KeyDecision(KeyClass.EDIT, trs)
        if key in CHAT_EDIT_KEYS:
            # Editing refreshes the TTL even when the key is bound; the
            # concurrent-hold demote rule still outranks it via on_tick.
            self._last_chat_evidence = now
            if self._state is ChatState.CAPTURE_SOFT:
                return KeyDecision(KeyClass.SUPPRESS)
            return KeyDecision(KeyClass.TYPING)
        if is_bound and not _is_typeable(key):
            # A bound action tap (F-key, Prior/Next, ...) is impossible as
            # chat content: demote immediately, then route the key under the
            # new state (the user is playing). space is exempt: it is typed
            # at every word boundary (see _TYPEABLE_MULTICHAR).
            return KeyDecision(KeyClass.MOVEMENT, self._go(ChatState.GRACE, "demote_tap", now))
        if not is_bound and _is_printable_char(key):
            self._note_typing_evidence(now)
        self._open_had_typing = True
        if self._state is ChatState.CAPTURE_SOFT:
            return KeyDecision(KeyClass.SUPPRESS)
        return KeyDecision(KeyClass.TYPING)

    def _keydown_route_or_grace(self, key, now, ctx, is_bound, is_chord) -> KeyDecision:
        if is_chord:
            if is_bound:
                # Open-chord key bound in a keyset: movement wins outside a
                # capture (documented residual; chat capture is disabled for
                # such configs and the keymap editor should flag it).
                return KeyDecision(KeyClass.MOVEMENT)
            return self._classify_chord(key, now)

        if key == "Escape":
            if is_bound:
                return KeyDecision(KeyClass.MOVEMENT)  # CC book in play
            self._context_active = False
            return KeyDecision(KeyClass.ESCAPE_CLEAR)

        if key == "BackSpace":
            return KeyDecision(KeyClass.EDIT, self._note_typing_evidence(now))

        if is_bound:
            # GRACE included: bound keys route INSTANTLY after a close (the
            # tap-deferral experiment is DISPROVEN — see the module note).
            return KeyDecision(KeyClass.MOVEMENT)

        if _is_printable_char(key):
            if ctx.mode_b:
                # Deterministic: the game opens chat on this letter. The
                # letter itself is the mirrored open key.
                tr = self._go(ChatState.CAPTURE, "mode_b_letter", now)
                self._open_had_typing = True
                return KeyDecision(KeyClass.CHORD_OPEN, tr, open_key=key)
            return KeyDecision(KeyClass.TYPING)

        return KeyDecision(KeyClass.ACTION)

    def on_keyup(self, key: str, now: float, ctx: ChatCtx) -> UpResult:
        if key in MODIFIER_KEYS:
            name = _MOD_NAME.get(key)
            if name and self._mods_down.get(name):
                self._mods_down[name] -= 1
                if self._mods_down[name] <= 0:
                    del self._mods_down[name]
            return UpResult()

        down_at = self._down.pop(key, None)
        self._unbound_printable_down.discard(key)

        transitions: tuple = ()
        if (down_at is not None
                and down_at > self._last_chord_at
                and key not in ctx.bound_keys
                and _is_printable_char(key)
                and now - down_at < self.config.tap_max):
            transitions = self._note_typing_evidence(now)

        return UpResult(transitions)

    def on_tick(self, now: float, ctx: ChatCtx) -> TickResult:
        cfg = self.config
        transitions: list = []

        if self.in_capture:
            demote = self._gameplay_demote_cause(now, ctx)
            if demote:
                transitions.extend(self._go(ChatState.GRACE, demote, now))
            elif (self._last_chat_evidence
                    and now - self._last_chat_evidence > cfg.capture_ttl):
                transitions.extend(self._go(ChatState.GRACE, "ttl", now))
        elif self._state is ChatState.GRACE:
            if now - self._state_entered >= cfg.grace_s:
                transitions.extend(self._go(ChatState.ROUTE, "grace_end", now))
        elif self._state is ChatState.ROUTE and self._context_active:
            # Gameplay contradiction clears a lingering context so a much
            # later chord cannot misread as SEND.
            if self._gameplay_demote_cause(now, ctx):
                self._context_active = False

        return TickResult(tuple(transitions))

    def on_focus_change_managed(self, now: float) -> tuple:
        """Focus moved between managed game windows. Mid-capture, the box
        believed open belongs to the PREVIOUS window; the caller must Escape
        it (or routed movement would type into it) and run the orphan guard
        for bg_chat_open."""
        if self.in_capture:
            return self._go(ChatState.GRACE, "focus_switch", now)
        return ()

    def force_route(self, now: float) -> tuple:
        """Cleanup / release_all_keys / strict-toggle / service lifecycle.
        Cheap idempotent no-op when already ROUTE (the cleanup branch calls
        this at ~100Hz — nothing here may allocate or scan in that case
        beyond the state check). From a capture, the CALLER must run the
        orphan guard (close key to bg_chat_open) — signalled by the
        returned transition."""
        if self._state is ChatState.ROUTE:
            if self._down or self._context_active:
                self._reset_volatile()
            return ()
        tr = self._go(ChatState.ROUTE, "force", now)
        self._reset_volatile()
        return tr

    def force_capture(self, now: float) -> tuple:
        """Compat/test seam for the legacy `global_chat_active = True`
        attribute write: force the machine into CAPTURE without running any
        side effects (seeding only — the caller's transition executor owns
        drains/grab resync)."""
        return self._go(ChatState.CAPTURE, "forced", now)

    def force_capture_soft(self, now: float) -> tuple:
        """Compat/test seam for the legacy `_phantom_active = True` write."""
        return self._go(ChatState.CAPTURE_SOFT, "forced", now)

    # ── internals ────────────────────────────────────────────────────────

    def _reset_volatile(self) -> None:
        self._down.clear()
        self._mods_down.clear()
        self._typing_events.clear()
        self._unbound_printable_down.clear()
        self._context_active = False

    def _matches_chord(self, key: str, ctx: ChatCtx) -> bool:
        held = set(self._mods_down)
        for mods, chord_key in ctx.open_chords:
            if key == chord_key and mods <= held:
                return True
        return False

    def _classify_chord(self, key: str, now: float) -> KeyDecision:
        self._last_chord_at = now
        if self.context_active(now):
            # SEND: the chord follows typing — it can never open. Consume
            # the context so the NEXT chord (with no typing between) reads
            # as a fresh OPEN.
            self._context_active = False
            self._typing_events.clear()
            return KeyDecision(KeyClass.CHORD_SEND)
        tr = self._go(ChatState.CAPTURE, "chord_open", now)
        self._open_had_typing = False
        return KeyDecision(KeyClass.CHORD_OPEN, tr, open_key=key)

    def _note_typing_evidence(self, now: float) -> tuple:
        cfg = self.config
        self._context_active = True
        self._context_last = now
        self._last_chat_evidence = now
        self._typing_events.append(now)
        while self._typing_events and now - self._typing_events[0] > cfg.burst_window:
            self._typing_events.popleft()
        if (len(self._typing_events) >= cfg.burst_n
                and self._state in (ChatState.ROUTE, ChatState.GRACE)):
            return self._go(ChatState.CAPTURE_SOFT, "burst", now)
        return ()

    def _gameplay_demote_cause(self, now: float, ctx: ChatCtx) -> Optional[str]:
        """Physically-impossible-as-chat signatures. Modifiers never
        participate (holding Shift while typing capitals is normal chat —
        they are not tracked in _down at all). Single chat-edit holds never
        demote (cursor editing); two concurrent bound holds always do
        (diagonal movement)."""
        cfg = self.config
        concurrent = []
        for key, t0 in self._down.items():
            if key not in ctx.bound_keys:
                continue
            held = now - t0
            if key not in CHAT_EDIT_KEYS and held >= cfg.t_demote:
                return "demote_hold"
            if held >= cfg.chord_min_hold:
                concurrent.append(t0)
        if len(concurrent) >= 2:
            concurrent.sort()
            if now - concurrent[-1] >= cfg.chord_overlap:
                return "demote_chord"
        return None

    def _go(self, new: ChatState, cause: str, now: float) -> tuple:
        old = self._state
        if old is new:
            return ()
        self._state = new
        self._state_entered = now
        if new in (ChatState.CAPTURE, ChatState.CAPTURE_SOFT):
            self._last_chat_evidence = now
        else:
            self._context_active = False
            self._typing_events.clear()
        return (Transition(old, new, cause),)
