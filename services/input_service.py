from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from functools import lru_cache
from PySide6.QtCore import QObject, Signal

from services.chat_fsm import ChatCtx, ChatFsm, ChatState, KeyClass
from utils.cc_isolation import MOVEMENT_ACTIONS as _MOVEMENT_ACTIONS
from utils.held_key_registry import HoldKind, HeldKeyRegistry
from utils.key_registry import NAMED_KEYSYMS_FROM_REGISTRY, PASSTHROUGH_KEYSYMS
from utils.input_trace import trace as _itrace, ENABLED as _ITRACE
# Re-exported so existing `from services.input_service import STRICT_TTR_SEPARATION`
# call sites keep working; the canonical home is utils/settings_keys.py.
from utils.settings_keys import STRICT_TTR_SEPARATION

WASD_KEYS     = frozenset({'w', 'a', 's', 'd'})
MOVEMENT_KEYS = WASD_KEYS | frozenset({'Up', 'Down', 'Left', 'Right', 'space'})
ARROW_KEYS    = frozenset({'Up', 'Down', 'Left', 'Right'})
ARROW_TO_WASD = {'Up': 'w', 'Down': 's', 'Left': 'a', 'Right': 'd'}

MODIFIER_KEYS = frozenset({'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R'})
MODIFIER_PREFIX = {
    'Shift_L': 'shift', 'Shift_R': 'shift',
    'Control_L': 'ctrl', 'Control_R': 'ctrl',
    'Alt_L': 'alt', 'Alt_R': 'alt',
}

# Alias so the existing _KEYSYM_LOOKUP.update(NAMED_KEYSYMS) line below works unchanged.
# The registry adds Home, End, Prior, Next, Insert to what was previously here.
NAMED_KEYSYMS: dict[str, str] = NAMED_KEYSYMS_FROM_REGISTRY

CHAR_TO_PHYSICAL_KEYSYM = {
    **{c: c for c in 'abcdefghijklmnopqrstuvwxyz'},
    **{c: c for c in '0123456789'},
    '-': 'minus',        '=': 'equal',
    '[': 'bracketleft',  ']': 'bracketright',
    '\\': 'backslash',   ';': 'semicolon',
    "'": 'apostrophe',   ',': 'comma',
    '.': 'period',       '/': 'slash',
    '`': 'grave',
    '!': '1',  '@': '2',  '#': '3',  '$': '4',  '%': '5',
    '^': '6',  '&': '7',  '*': '8',  '(': '9',  ')': '0',
    '_': 'minus',        '+': 'equal',
    '{': 'bracketleft',  '}': 'bracketright',
    '|': 'backslash',    ':': 'semicolon',
    '"': 'apostrophe',   '<': 'comma',
    '>': 'period',       '?': 'slash',
    '~': 'grave',
}

# Fix #8: Pre-built combined lookup dict for O(1) keysym resolution
_KEYSYM_LOOKUP = {}
_KEYSYM_LOOKUP.update(NAMED_KEYSYMS)
_KEYSYM_LOOKUP.update(CHAR_TO_PHYSICAL_KEYSYM)
# Add lowercase alpha mappings (handles the .lower() case)
for c in 'abcdefghijklmnopqrstuvwxyz':
    _KEYSYM_LOOKUP[c] = CHAR_TO_PHYSICAL_KEYSYM[c]


def _resolve_keysym(key):
    """Module-level send-time keysym resolver. O(1) lookup from the
    pre-built _KEYSYM_LOOKUP. Returns the X11 keysym string for a stored
    key, or None if unmapped. The InputService method below delegates here
    so both the instance call sites and registry tests share one resolver."""
    result = _KEYSYM_LOOKUP.get(key)
    if result:
        return result
    if len(key) == 1 and key.isalpha():
        return _KEYSYM_LOOKUP.get(key.lower())
    return None





class InputService(QObject):
    log_signal = Signal(str)
    input_log = Signal(str)
    window_ids_updated = Signal(list)
    chat_state_changed = Signal(bool)  # True = chat active, False = chat inactive
    uipi_blocked_movement_detected = Signal(object)  # details dict for the elevation modal

    BACKSPACE_REPEAT_DELAY    = 0.4
    BACKSPACE_REPEAT_INTERVAL = 0.05
    AUTO_REPEAT_DEDUP_WINDOW  = 0.015

    def __init__(self, window_manager, get_enabled_toons, get_movement_modes, get_event_queue_func,
                 get_chat_enabled=None, settings_manager=None,
                 get_keymap_assignments=None, keymap_manager=None,
                 get_chat_block_list=None, get_chat_handling_mode=None,
                 capability_provider=None):
        super().__init__()
        self.window_manager = window_manager
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_event_queue = get_event_queue_func
        self.get_chat_enabled = get_chat_enabled
        self.settings_manager = settings_manager
        self.get_keymap_assignments = get_keymap_assignments
        self.keymap_manager = keymap_manager
        # Per-window UIPI delivery capability (Windows only). On Windows the hot
        # path reads a cached snapshot via peek(); focus/assignment handlers
        # refresh via the cache's get(). Off Windows the feature is a no-op: the
        # provider resolves to OK directly (no cache), so strict separation and
        # every other capability check behave exactly as before this feature.
        # Tests inject a provider directly (no cache).
        from utils.win32_integrity import _IS_WINDOWS, Capability, WindowCapabilityCache
        if capability_provider is not None:
            self._capability_provider = capability_provider
            self._capability_cache = None
        elif not _IS_WINDOWS:
            self._capability_cache = None
            self._capability_provider = lambda w: Capability.OK
        else:
            self._capability_cache = WindowCapabilityCache()
            self._capability_provider = lambda w: self._capability_cache.peek(int(w))
        # Resolved per call so changes to TTR's settings.json after service start
        # are honored without restarting the input thread. Default preserves the
        # legacy hard-coded behavior for callers that don't wire the helper.
        self.get_chat_block_list = get_chat_block_list or (lambda: {"Return", "Escape"})
        self.get_chat_handling_mode = get_chat_handling_mode
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self.logging_enabled = False

        # ── Chat gate FSM (DEFAULT ON; TTMT_CHAT_FSM=0 = legacy kill switch)
        # Redesign of the chat-open inference; see
        # docs/superpowers/plans/2026-07-03-chat-fsm-redesign.md. Default
        # flipped 2026-07-03 after Fedora live validation. With the kill
        # switch: the legacy Return-toggle/phantom path runs unchanged and
        # the global_chat_active/_phantom_active properties read/write plain
        # backing fields, so every legacy writer and test seed keeps
        # working. FSM mode: the properties reflect/force FSM state. The
        # legacy path (and this switch) is deleted after one beta cycle.
        self._fsm_enabled = os.environ.get("TTMT_CHAT_FSM", "1") != "0"
        self._chat_fsm: ChatFsm | None = ChatFsm() if self._fsm_enabled else None
        self._legacy_global_chat_active = False
        self._legacy_phantom_active = False
        # Window ids of background chat boxes WE opened by mirroring an
        # open chord (mirror modes only). Scoped close/orphan Escapes
        # target exactly this set; window-id keyed because toon indices
        # remap whenever assign_windows re-sorts.
        self._bg_chat_open: set = set()
        # FSM-mode autorepeat guard: Windows delivers repeated WM_KEYDOWNs
        # for a held key; a repeat must not reset the FSM's hold-duration
        # tracking (750ms demote would never fire).
        self._fsm_seen_down: set = set()
        # True only during the FSM capture-entry drain: lets the drain's
        # keyups (for keydowns dispatched pre-capture) pass the
        # global_chat_active gate in _send_logical_action_km.
        self._fsm_draining = False
        # Previous managed game window, for the focus-switch-mid-capture
        # hook (the open box belongs to the PREVIOUS window).
        self._fsm_prev_game_window = None
        # Wired post-construction (main.py) like get_chat_block_list;
        # resolves TTR's configured chat/groupChat chords per event.
        self.get_chat_open_chords = None

        self.holds = HeldKeyRegistry()
        self.bg_typing_held = set()
        self.chat_active = set()
        self.global_chat_active = False

        # Phantom chat detection — catches whisper replies opened via mouse click
        self._phantom_char_count = 0
        self._phantom_active = False
        self._chat_last_activity = 0.0
        self.CHAT_IDLE_TIMEOUT = 15.0

        self._xlib = None
        # _xlib_backend_failed: True when a REQUESTED delivery backend could not
        # be initialized (import, construct, or connect) -- the xlib backend on
        # Linux (input_backend == "xlib") or the Win32 backend on Windows.
        # Distinct from the user explicitly selecting the xdotool backend on
        # Linux. _send_via_backend reads this to REFUSE a silent xdotool/XTEST
        # fallback, which would re-trigger the Wayland input-control portal the
        # app deliberately avoids (and can stick an auto-repeating key).
        self._xlib_backend_failed = False
        # One-shot guard so the "input delivery disabled" surfacing fires once
        # per failure episode, not on every dropped keystroke. Reset whenever a
        # working backend is (re)established.
        self._xlib_unavailable_logged = False
        # Focused-toon passthrough delivery (strict TTR). Maps a key to the
        # (window, keysym) its keydown was actually sent to, so the release is
        # paired to the exact target regardless of later focus/strict/chat
        # changes. Delivered via the reliable pynput/XRecord path because the
        # grabber's X stream is lossy under XWayland. See
        # docs/superpowers/specs/2026-06-02-focused-passthrough-delivery-design.md
        # Accessed from the run-loop thread (record on keydown, release on the
        # keyup flush) and, on focus change / shutdown, from the GUI/settings
        # thread via _drain_focused_passthrough. Intentionally unguarded: dict
        # set/pop are atomic under the GIL, and a focus-change drain racing a
        # keydown can at worst send a paired keyup right after the keydown,
        # which is the desired focus-away behavior (no corruption, no double-send).
        self._focused_passthrough_sent: dict[str, tuple[str, str]] = {}
        self._key_grabber = None
        # Fired (if set) right after _key_grabber is created and BEFORE the seed
        # focus call, so main can wire hotkey interop before route_all can arm.
        self.grabber_created_callback = None
        # True only while movement grabs are actually INSTALLED for a focused
        # TTR preset window. Set by _on_active_window_changed_for_grabber. Gates
        # the focused-window synth in _send_logical_action_km so we never
        # synthesize to a focused window whose physical key isn't suppressed.
        self._ttr_grabs_active = False
        # Whether the CURRENT focus should be under TTR strict suppression.
        # Set by the focus handler; read by the grabber's on_grabs_changed
        # callback (which owns _ttr_grabs_active) so the gate reflects real grab
        # state rather than enqueue-time intent.
        self._intended_ttr_strict = False
        # Transient flag: True only during an explicit synchronous drain that
        # fires while strict is being torn down (toggle-off or capture-open).
        # Allows the focused-window keyup to pass through _send_logical_action_km
        # even though _strict_ttr_active() is already False at that point, so
        # the focused toon's synthesized keydown is properly balanced.
        self._strict_drain_active: bool = False

        # Track the most recent foreground game so keys pressed while TTMT
        # itself has focus still resolve through a meaningful default set.
        self._last_known_foreground_game: str | None = None

        # UIPI blocked-movement episode counter + deferred modal signal state.
        import time as _t_uipi
        self._uipi_clock = _t_uipi.monotonic
        self._uipi_latched = False
        self._uipi_episodes: dict[str, list[float]] = {}   # win_id -> [timestamps]
        self._uipi_holds: dict[str, tuple[str, float]] = {}  # key -> (win_id, down_ts)
        self._uipi_pending = None    # details dict awaiting release before emit
        self._uipi_refresh_timer = None  # periodic off-hot-path capability refresh
        self._uipi_refresh_wired = False  # window_ids_updated connected once
        self.UIPI_WINDOW_SECONDS = 5.0
        self.UIPI_HOLD_SECONDS = 0.75

    @property
    def keys_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.MOVEMENT))

    @property
    def modifiers_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.MODIFIER))

    @property
    def action_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.ACTION))

    # ── chat-state compat aliases ────────────────────────────────────────
    # Every enforcement seam (routing early-return, consume predicate, focus
    # handler, UIPI disarm) and ~24 test seed sites read/write these names.
    # Legacy mode: plain backing fields, bit-identical behavior. FSM mode:
    # reads reflect FSM state (CAPTURE / CAPTURE_SOFT); writes FORCE the FSM
    # without running capture side effects — _set_chat_active and the FSM
    # transition applier own drains/grab resync.

    @property
    def global_chat_active(self) -> bool:
        if self._fsm_enabled:
            return self._chat_fsm.state is ChatState.CAPTURE
        return self._legacy_global_chat_active

    @global_chat_active.setter
    def global_chat_active(self, value) -> None:
        self._legacy_global_chat_active = bool(value)
        if self._fsm_enabled:
            if value:
                self._chat_fsm.force_capture(time.monotonic())
            elif self._chat_fsm.state is ChatState.CAPTURE:
                self._chat_fsm.force_route(time.monotonic())

    @property
    def _phantom_active(self) -> bool:
        if self._fsm_enabled:
            return self._chat_fsm.state is ChatState.CAPTURE_SOFT
        return self._legacy_phantom_active

    @_phantom_active.setter
    def _phantom_active(self, value) -> None:
        self._legacy_phantom_active = bool(value)
        if self._fsm_enabled:
            if value:
                self._chat_fsm.force_capture_soft(time.monotonic())
            elif self._chat_fsm.state is ChatState.CAPTURE_SOFT:
                self._chat_fsm.force_route(time.monotonic())

    def start(self):
        if self.running and self.thread is not None and self.thread.is_alive():
            return
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=False)
        self.thread.start()
        self._start_key_grabber()
        self._start_uipi_refresh()

    def _start_key_grabber(self) -> None:
        """Install the platform-appropriate movement key grabber in
        focus-aware mode.

        Linux gate: only when an X11 display is available. The grabber now
        arms for CC OR TTR windows, controlled per-focus by
        _on_active_window_changed_for_grabber; the actual passive XGrabKeys are
        installed/uninstalled there. Without a display, strict separation
        degrades to a no-op.

        Windows gate: only the platform check. The Win32 grabber is purely
        a state machine queried by HotkeyManager's pynput hook; there is
        nothing to install at the OS level.

        Common lifecycle: prepare() at startup, install_grabs only while a
        CC or TTR window has focus, uninstall on focus-change away. The
        canonical set is the focused toon's assigned set.
        """
        if self._key_grabber is not None:
            return  # already initialized; stop()/start() cycle preserves the grabber

        import sys as _sys

        if _sys.platform == "win32":
            from utils.win32_movement_grabber import Win32MovementKeyGrabber
            grabber = Win32MovementKeyGrabber()
            ok = grabber.prepare(
                should_consume=self._should_consume_grabbed_key,
                on_grabs_changed=self._on_grabs_changed,
            )
            if not ok:
                return
            self._key_grabber = grabber
        elif _sys.platform == "darwin":
            from utils.macos_movement_grabber import MacOSMovementKeyGrabber
            grabber = MacOSMovementKeyGrabber()
            ok = grabber.prepare(
                should_consume=self._should_consume_grabbed_key,
                on_grabs_changed=self._on_grabs_changed,
            )
            if not ok:
                return
            self._key_grabber = grabber
        else:
            try:
                from utils.x11_movement_grabber import MovementKeyGrabber, xlib_available
            except ImportError as e:
                print(f"[InputService] key grabber unavailable: {e}")
                return
            if not xlib_available():
                return  # no X11 display: strict separation degrades to no-op
            grabber = MovementKeyGrabber()
            ok = grabber.prepare(
                on_key=self._on_grabbed_key,
                should_consume=self._should_consume_grabbed_key,
                on_passthrough=self._on_passthrough_key,
                on_grabs_changed=self._on_grabs_changed,
            )
            if not ok:
                return
            self._key_grabber = grabber

        cb = getattr(self, "grabber_created_callback", None)
        if cb is not None:
            try:
                cb()          # main wires hotkey interop before the seed can arm route_all
            except Exception:
                pass

        # Subscribe to focus changes; seed with current focus. (Both
        # platforms share this wiring because both grabbers honor
        # install_grabs/uninstall_grabs.)
        try:
            self.window_manager.active_window_changed.connect(
                self._on_active_window_changed_for_grabber
            )
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] active_window_changed connect failed: {e}")
        try:
            seed = self.window_manager.get_active_window()
        except Exception:
            seed = None
        self._on_active_window_changed_for_grabber(seed or "")
        if self.settings_manager is not None:
            try:
                self.settings_manager.on_change(self._on_strict_ttr_setting_changed)
            except Exception as e:  # noqa: BLE001
                print(f"[InputService] settings on_change connect failed: {e}")

    def _canonical_set_for_toon_index(self, toon_index: int) -> str | None:
        """Return 'wasd' or 'arrows' for the keyset assigned to the toon at
        toon_index, for whichever game that toon's window belongs to. Returns
        None for any non-preset set (which causes the grabber to uninstall and
        the window to fall back to today's behavior).

        Staleness note: changes to the focused toon's assignment are picked up
        on the NEXT focus-change event, not live.
        """
        if self.keymap_manager is None:
            return None
        try:
            window_ids = self.window_manager.get_window_ids()
        except Exception:
            return None
        if toon_index < 0 or toon_index >= len(window_ids):
            return None
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(
                str(window_ids[toon_index])
            )
        except Exception:
            game = None
        if game is None:
            return None
        try:
            assignments = self._get_assignments(self.get_enabled_toons())
        except Exception:
            return None
        if toon_index >= len(assignments):
            return None
        set_idx = assignments[toon_index]
        try:
            forward = self.keymap_manager.get_key_for_action(game, set_idx, "forward")
        except Exception:
            return None
        if forward == "w":
            return "wasd"
        if forward == "Up":
            return "arrows"
        return None

    def _on_active_window_changed_for_grabber(self, window_id: str) -> None:
        """Slot for WindowManager.active_window_changed. Installs grabs for the
        focused CC or TTR toon's keyset, or uninstalls them. Records
        self._intended_ttr_strict (whether the focused window SHOULD be under TTR
        strict suppression); the grabber's on_grabs_changed callback then sets
        self._ttr_grabs_active once grabs ACTUALLY change, so the router never
        synthesizes to a focused TTR window whose keys aren't yet suppressed.
        """
        # FSM hook, BEFORE the chat/phantom grabs-off branch below: a focus
        # switch between managed game windows during a capture means the box
        # believed open belongs to the PREVIOUS window. Escape it (routed
        # movement would otherwise type into it), run the orphan guard, and
        # drop to GRACE — the properties then read False so this handler
        # proceeds with a normal install for the new window.
        self._fsm_handle_focus_change(window_id)
        # Record intent before any grabber call so the (possibly synchronous in
        # tests, async in production) completion callback observes the right
        # value. Default: not a TTR strict focus.
        _prev_intent = self._intended_ttr_strict
        self._intended_ttr_strict = False
        # Any focus change releases held focused-passthrough keys to the window
        # they were sent to, so a modifier/char is never left down on the old
        # focused toon when focus moves.
        self._drain_focused_passthrough()
        if self._key_grabber is None:
            if _ITRACE:
                _itrace("focus", f"win={window_id!r} no-grabber intent {_prev_intent}->False")
            return
        if not window_id:
            if _ITRACE:
                _itrace("focus", f"win=<empty> uninstall intent {_prev_intent}->False")
            self._key_grabber.uninstall_grabs()
            return
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(str(window_id))
        except Exception:
            game = None
        # Refresh the UIPI capability of EVERY enabled managed game window off the
        # hot path, so both the focused-window delivery-safe gate AND the
        # background-window modal trigger (which read via peek) see fresh values.
        # Refreshing only the focused window would leave never-focused background
        # targets stuck at UNKNOWN, so the blocked-movement modal would never fire
        # for an elevated background game (the feature's primary case).
        self._refresh_uipi_capabilities()
        # TTR strict separation is supported on Linux/X11, Windows, and macOS;
        # other platforms keep pre-feature behavior (_ttr_strict_supported).
        if game == "ttr" and not (
            self._strict_ttr_enabled()
            and self._ttr_strict_supported()
            and self._focused_strict_delivery_safe()
        ):
            if _ITRACE:
                _itrace("focus", f"win={window_id} game=ttr strict-unsupported uninstall "
                                 f"intent {_prev_intent}->False")
            self._key_grabber.uninstall_grabs()
            return
        if game not in ("cc", "ttr"):
            if _ITRACE:
                _itrace("focus", f"win={window_id} game={game} non-game uninstall "
                                 f"intent {_prev_intent}->False")
            self._key_grabber.uninstall_grabs()
            return
        try:
            window_ids = self.window_manager.get_window_ids()
            toon_index = next(
                (i for i, w in enumerate(window_ids) if str(w) == str(window_id)),
                -1,
            )
        except Exception:
            toon_index = -1
        if toon_index < 0:
            if _ITRACE:
                _itrace("focus", f"win={window_id} game={game} toon_index<0 uninstall "
                                 f"intent {_prev_intent}->False")
            self._key_grabber.uninstall_grabs()
            return
        canonical = self._canonical_set_for_toon_index(toon_index)
        if canonical is None:
            if _ITRACE:
                _itrace("focus", f"win={window_id} game={game} idx={toon_index} canonical=None "
                                 f"uninstall intent {_prev_intent}->False")
            self._key_grabber.uninstall_grabs()
            return
        # Set intent BEFORE install so on_grabs_changed credits this as a TTR
        # strict focus. CC focus installs the same way but intent stays False
        # (CC has its own always-on routing and must not flip the TTR gate).
        self._intended_ttr_strict = (game == "ttr")
        if game == "ttr":
            # Linux (X11 passive grab), Windows (Win32 LL hook), and macOS
            # (darwin_intercept filter), gated above: route both keysets,
            # suppress native delivery.
            if self.global_chat_active or self._phantom_active:
                # Input capture (chat/whisper) is active: keep grabs OFF so
                # keystrokes land natively in the focused TTR window. Intent
                # stays True so the capture-close resync reinstalls route_all.
                if _ITRACE:
                    _itrace("focus", f"win={window_id} ttr idx={toon_index} chat/phantom-> grabs OFF "
                                     f"intent {_prev_intent}->True (chat={self.global_chat_active} "
                                     f"phantom={self._phantom_active})")
                self._key_grabber.uninstall_grabs()
                return
            if _ITRACE:
                _itrace("focus", f"win={window_id} ttr idx={toon_index} install route_all "
                                 f"intent {_prev_intent}->True")
            passthrough = list(_passthrough_keysyms_for_canonical(canonical))
            # Every key bound in ANY of the foreground game's sets must be
            # suppressed, not just the 8 preset movement keys: an unsuppressed
            # bound key reaches the focused client natively (raw Alt_R read as
            # the side-agnostic 'alt' book binding) AND the router refuses to
            # synthesize its action to the focused toon (double-delivery
            # guard), so rebound non-movement keys were dead for the focused
            # toon on Windows. Same union the router uses for is_movement, so
            # suppression and re-synthesis stay in lockstep. The X11 grabber
            # ignores route_keys (its whole-keyboard grab already covers all).
            route_keys = None
            if self.keymap_manager is not None:
                try:
                    route_keys = self.keymap_manager.get_keys_for_game(game)
                except Exception:
                    route_keys = None
            self._key_grabber.install_grabs(
                canonical_set=canonical, passthrough_keysyms=passthrough,
                route_all=True, route_keys=route_keys)
        else:
            # CC: legacy path. Omit route_all so CC keeps opposite-keyset-only
            # suppression on both platforms; both grabbers default route_all=False.
            if _ITRACE:
                _itrace("focus", f"win={window_id} cc idx={toon_index} install legacy "
                                 f"intent {_prev_intent}->False")
            passthrough = list(_passthrough_keysyms_for_canonical(canonical))
            self._key_grabber.install_grabs(
                canonical_set=canonical, passthrough_keysyms=passthrough)

    def _on_grabs_changed(self, canonical) -> None:
        """Called by the grabber AFTER grabs actually change (worker thread on
        Linux). Sets _ttr_grabs_active to reflect REAL suppression state, not the
        enqueue-time intent: True only when the latest focus intends TTR strict
        AND a grab is now installed (canonical is not None) AND the platform
        supports it. This closes the enqueue-vs-install timing gap."""
        self._ttr_grabs_active = bool(
            self._intended_ttr_strict
            and canonical is not None
            and self._ttr_strict_supported()
        )
        if _ITRACE:
            _itrace("grabs_changed", f"canonical={canonical} intent={self._intended_ttr_strict} "
                                     f"-> ttr_grabs_active={self._ttr_grabs_active}")

    def _on_strict_ttr_setting_changed(self, key: str = "", value=None) -> None:
        """React to the strict_ttr_separation toggle changing at runtime.
        Release any held keys (so a toon isn't left walking when grabs are torn
        down), then re-seed the grabber for the current focus. settings_manager
        broadcasts (key, value) for every change, so ignore unrelated keys."""
        if key and key != STRICT_TTR_SEPARATION:
            return
        try:
            self._strict_drain_active = True
            self.release_all_keys()
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] release_all_keys on toggle failed: {e}")
        finally:
            self._strict_drain_active = False
        try:
            seed = self.window_manager.get_active_window()
        except Exception:
            seed = None
        try:
            self._on_active_window_changed_for_grabber(seed or "")
        except Exception as e:  # noqa: BLE001
            # This runs inside settings_manager's change-callback loop; never let
            # a reseed failure propagate and break other listeners.
            print(f"[InputService] grabber reseed on toggle failed: {e}")

    def _on_grabbed_key(self, action: str, keysym: str) -> None:
        """Forward a consumed grab event into the same queue pynput uses."""
        if _ITRACE:
            _itrace("grabbed_enqueue", f"action={action} keysym={keysym}")
        try:
            event_queue = self.get_event_queue()
            if event_queue is not None:
                event_queue.put_nowait((action, keysym))
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] enqueue from grabber failed: {e}")

    def _on_passthrough_key(self, action: str, keysym: str) -> None:
        """Hand a non-grabbed key that arrived during an active grab back to the
        focused game window (X redirects all keyboard events to the grabbing
        client during an active grab). CC routes via the wine bridge and TTR via
        native X11 -- both handled by _send_via_backend.
        """
        try:
            active = self.window_manager.get_active_window()
        except Exception:
            return
        if not active:
            return
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(str(active))
        except Exception:
            return
        if game not in ("cc", "ttr"):
            return
        if game == "ttr" and not (self._strict_ttr_enabled() and self._ttr_strict_supported()):
            if _ITRACE:
                _itrace("passthru", f"action={action} keysym={keysym} active={active} "
                                    f"game={game} -> SKIP (ttr strict off/unsupported)")
            return
        if _ITRACE:
            _itrace("passthru", f"action={action} keysym={keysym} active={active} "
                                f"game={game} -> send")
        try:
            self._send_via_backend(action, str(active), keysym)
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] passthrough send failed: {e}")

    def _focused_ttr_window(self) -> str | None:
        """Return the active window id when strict TTR separation is ACTIVE
        (native delivery suppressed) AND the active window is a TTR window;
        else None. Shared gate for the focused-passthrough send helpers.
        Exception-safe: any failure resolves to None (no-op delivery)."""
        try:
            if not self._strict_ttr_active():
                return None
            # Focused-passthrough exists only because the X11 active grab steals
            # ALL keyboard events. A grabber that does not redirect everything
            # (the Win32 non-exclusive hook) lets non-movement keys reach the
            # focused window natively; re-sending them would double them.
            grabber = self._key_grabber
            if grabber is not None and not getattr(
                grabber, "needs_focused_passthrough", True
            ):
                return None
            active = self.window_manager.get_active_window()
            if not active:
                return None
            from utils.game_registry import GameRegistry
            if GameRegistry.instance().get_game_for_window(str(active)) != "ttr":
                return None
            return str(active)
        except Exception:
            return None

    def _send_passthrough_to_focused(self, key: str) -> None:
        """Deliver a non-movement key to the focused TTR window via the reliable
        pynput-driven path (XSendEvent), recording it for a paired release. The
        grabber's passthrough re-send is lossy under XWayland; this is the
        reliable replacement. No-op unless strict is active + active is TTR."""
        active = self._focused_ttr_window()
        if active is None:
            return
        # Defensive: a duplicate keydown without an intervening release would
        # orphan the prior record (and could leave that key down on the old
        # target). Release any stale entry first so every keydown is paired.
        if key in self._focused_passthrough_sent:
            self._release_focused_passthrough(key)
        keysym = self._resolve_keysym(key) or key
        self._focused_passthrough_sent[key] = (active, keysym)
        if _ITRACE:
            _itrace("focus_passthru",
                    f"keydown key={key} keysym={keysym} target={active}")
        try:
            self._send_via_backend("keydown", active, keysym)
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] focused passthrough keydown failed: {e}")

    def _release_focused_passthrough(self, key: str) -> None:
        """Release a previously-delivered focused passthrough key to the SAME
        (window, keysym) its keydown was sent to, regardless of current
        strict/active state. No-op if the key was not recorded as sent."""
        target = self._focused_passthrough_sent.pop(key, None)
        if target is None:
            return
        win, keysym = target
        if _ITRACE:
            _itrace("focus_passthru", f"keyup key={key} keysym={keysym} target={win}")
        try:
            self._send_via_backend("keyup", win, keysym)
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] focused passthrough keyup failed: {e}")

    def _drain_focused_passthrough(self) -> None:
        """Release every recorded focused passthrough key (focus-away /
        toggle-off / shutdown). Independent of HeldKeyRegistry, since
        Return/Escape/printables never enter `holds`."""
        for key in list(self._focused_passthrough_sent.keys()):
            self._release_focused_passthrough(key)

    # ------------------------------------------------------------------
    # UIPI blocked-movement episode counter + deferred modal signal
    # ------------------------------------------------------------------

    def _note_blocked_movement(self, win_id, action, key):
        """Record a movement-class action routed to a BACKGROUND target that is
        BLOCKED_UIPI.  Arms a pending modal when the debounce trips; the modal is
        emitted later by _release_uipi_hold so it never pops mid-hold.  Proof+intent:
        only fires when we can PROVE delivery is blocked AND the user is actively
        moving a background toon."""
        from utils.cc_isolation import MOVEMENT_ACTIONS
        from utils.win32_integrity import Capability
        if self._uipi_latched:
            return
        if key in self._uipi_holds:
            # Still held: a re-report of an already-held key is autorepeat, not a
            # new press. Do NOT count it as a second episode and do NOT touch the
            # original press timestamp (so the 750ms hold rule stays a true hold
            # timer measured from the real keydown). In production the run loop
            # dedupes autorepeat before dispatch, so this is defense in depth.
            return
        if action not in MOVEMENT_ACTIONS:
            return
        if self.global_chat_active or self._phantom_active or self._strict_drain_active:
            return
        try:
            active = self.window_manager.get_active_window()
            ids = [str(w) for w in self.window_manager.get_window_ids()]
        except Exception:
            return
        if not active or str(active) not in ids:
            return                       # active must be a managed game window (not TTMT)
        if str(win_id) == str(active):
            return                       # background targets only
        if self._capability_for(win_id) is not Capability.BLOCKED_UIPI:
            return
        now = self._uipi_clock()
        self._uipi_holds[key] = (str(win_id), now)
        stamps = [t for t in self._uipi_episodes.get(str(win_id), [])
                  if now - t <= self.UIPI_WINDOW_SECONDS]
        stamps.append(now)
        self._uipi_episodes[str(win_id)] = stamps
        if len(stamps) >= 2:
            self._arm_pending_uipi(str(win_id))

    def _release_uipi_hold(self, key):
        """On movement keyup: apply the held->750ms rule, then emit any pending
        modal once no blocked movement key remains held (so it never steals focus
        mid-hold).  Latch is set BEFORE emit so rapid events cannot queue dupes."""
        held = self._uipi_holds.pop(key, None)
        if held is not None and not self._uipi_latched:
            win_id, down_ts = held
            if self._uipi_clock() - down_ts >= self.UIPI_HOLD_SECONDS:
                self._arm_pending_uipi(win_id)
        if self._uipi_pending is not None and not self._uipi_holds:
            details = self._uipi_pending
            self._uipi_pending = None
            self._uipi_latched = True
            self.uipi_blocked_movement_detected.emit(details)

    def _arm_pending_uipi(self, win_id):
        if self._uipi_latched:
            return
        self._uipi_pending = self._build_uipi_details(win_id)

    def _build_uipi_details(self, primary_win_id):
        """Aggregate every enabled BACKGROUND game window currently BLOCKED_UIPI."""
        from utils.win32_integrity import Capability
        try:
            ids = [str(w) for w in self.window_manager.get_window_ids()]
            active = self.window_manager.get_active_window()
            enabled = self.get_enabled_toons()
        except Exception:
            ids, active, enabled = [], None, []
        targets = []
        for i, w in enumerate(ids):
            if i < len(enabled) and enabled[i] and str(w) != str(active):
                if self._capability_for(w) is Capability.BLOCKED_UIPI:
                    targets.append({"window_id": str(w), "toon_index": i})
        primary_idx = ids.index(str(primary_win_id)) if str(primary_win_id) in ids else -1
        return {"window_id": str(primary_win_id), "toon_index": primary_idx, "targets": targets}

    def reset_uipi_latch(self):
        """Re-arm detection (after a successful elevated relaunch attempt or a
        fresh service start)."""
        self._uipi_latched = False
        self._uipi_episodes.clear()
        self._uipi_holds.clear()
        self._uipi_pending = None

    def _send_backspace_to_focused(self) -> None:
        """Deliver a BackSpace key-tap to the focused TTR window. BackSpace uses
        a 'key' tap (like the bg path) rather than the keydown/keyup registry,
        so the repeat timer can re-send it; no paired release is needed."""
        active = self._focused_ttr_window()
        if active is None:
            return
        try:
            self._send_via_backend("key", active, "BackSpace")
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] focused passthrough BackSpace failed: {e}")

    def _should_consume_grabbed_key(self, keysym: str) -> bool:
        """Decide per-event whether to suppress the grabbed key from the
        focused window. Consume only when no typing capture is active AND the
        active window is a CC window, or a TTR window with strict separation
        on. The phantom/CAPTURE_SOFT check closes a documented gap: during a
        soft capture the grabs are (being) uninstalled, but this per-event
        predicate must never disagree with the capture state in the interim.
        """
        if self.global_chat_active or self._phantom_active:
            return False
        try:
            active = self.window_manager.get_active_window()
        except Exception:
            return False
        if not active:
            return False
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(str(active))
        except Exception:
            return False
        if game == "cc":
            return True
        if game == "ttr":
            return (
                self._strict_ttr_enabled()
                and self._ttr_strict_supported()
                and self._delivery_backend_ready()
                and self._focused_strict_delivery_safe()
            )
        return False

    def _suppress_predicate(self, keysym: str) -> bool:
        """Bridge from HotkeyManager's pynput callback to the platform
        grabber's should_suppress query. Returns False when no grabber
        is installed or the grabber doesn't expose should_suppress
        (Linux's MovementKeyGrabber does its own X-level suppression
        and has no should_suppress method)."""
        grabber = self._key_grabber
        if grabber is None:
            return False
        should_suppress = getattr(grabber, "should_suppress", None)
        if should_suppress is None:
            return False
        return bool(should_suppress(keysym))

    def grabber_keysym_for_vk(self, vk):
        """Bridge from HotkeyManager's win32 event filter to the grabber's
        dynamic vk -> keysym map (built from the installed grab set). None
        when no grabber, no map, or the vk is not grabbed; the filter then
        falls back to its static movement table."""
        grabber = self._key_grabber
        lookup = getattr(grabber, "keysym_for_vk", None)
        if lookup is None:
            return None
        try:
            return lookup(vk)
        except Exception:
            return None

    def _apply_backend_setting(self):
        """Connect or disconnect backend based on platform and current settings."""
        import sys
        if sys.platform == "darwin":
            if self._xlib is None:
                try:
                    from utils.macos_backend import MacOSBackend
                    self._xlib = MacOSBackend()
                    self._xlib.connect()
                    self._xlib_backend_failed = False
                    self._xlib_unavailable_logged = False
                except Exception as e:
                    print(f"[InputService] macOS input backend unavailable; "
                          f"synthetic input disabled: {e}")
                    self._xlib = None
                    self._xlib_backend_failed = True
                    # Leave _xlib_unavailable_logged as-is: it is reset only on
                    # recovery, so the drop message surfaces once per failure
                    # episode rather than every keystroke (mirrors win32/xlib).
                    if self.logging_enabled:
                        self.input_log.emit(
                            "[Input] Input delivery unavailable; the input backend failed to start."
                        )
            return

        if sys.platform == "win32":
            if self._xlib is None:
                try:
                    from utils.win32_backend import Win32Backend
                    self._xlib = Win32Backend()
                    self._xlib.connect()
                    self._xlib_backend_failed = False
                    self._xlib_unavailable_logged = False
                except Exception as e:
                    print(f"[InputService] input backend unavailable; synthetic "
                          f"input disabled (not emulating): {e}")
                    self._xlib = None
                    self._xlib_backend_failed = True
                    # Leave _xlib_unavailable_logged as-is: it is reset only on
                    # recovery, so the drop message surfaces once per
                    # failure episode rather than every keystroke.
                    if self.logging_enabled:
                        self.input_log.emit(
                            "[Input] Input delivery unavailable; the input backend failed to start."
                        )
            return

        use_xlib = (self.settings_manager.get("input_backend", "xlib") == "xlib") if self.settings_manager else True
        if use_xlib:
            if self._xlib is None:
                try:
                    from utils.xlib_backend import XlibBackend
                    self._xlib = XlibBackend()
                    self._xlib.connect()
                    self._xlib_backend_failed = False
                    self._xlib_unavailable_logged = False
                    if _ITRACE:
                        _itrace("backend", "xlib backend connected")
                except Exception as e:
                    # Do NOT fall back to xdotool/XTEST: that re-triggers the
                    # Wayland input-control portal the app deliberately avoids
                    # and can leave a stuck auto-repeating key. Disable
                    # synthetic input and surface the failure instead.
                    print(f"[InputService] input backend unavailable; synthetic "
                          f"input disabled (not emulating): {e}")
                    self._xlib = None
                    self._xlib_backend_failed = True
                    # Leave _xlib_unavailable_logged as-is: it is reset only on
                    # recovery, so the drop message surfaces once per
                    # failure episode rather than every keystroke.
                    if _ITRACE:
                        _itrace("backend", f"xlib connect FAILED: {e}")
                    if self.logging_enabled:
                        self.input_log.emit(
                            "[Input] Input delivery unavailable; the input backend failed to start."
                        )
        else:
            # User explicitly selected the xdotool backend (intended; the
            # settings UI warns about the Wayland portal on GNOME).
            if self._xlib is not None:
                self._xlib.disconnect()
                self._xlib = None
            self._xlib_backend_failed = False
            self._xlib_unavailable_logged = False

    def stop(self, wait: bool = False):
        self.running = False
        self._stop_event.set()
        if wait and self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def shutdown(self):
        """Call once on app exit to clean up the Xlib connection."""
        self.stop(wait=True)
        self._stop_uipi_refresh()
        if self._key_grabber is not None:
            try:
                self._key_grabber.stop()
            except Exception as e:
                print(f"[InputService] key grabber shutdown error: {e}")
            self._key_grabber = None
        self._ttr_grabs_active = False  # grabs are gone; keep the flag accurate
        self._intended_ttr_strict = False
        try:
            from utils import wine_input_bridge
            wine_input_bridge.shutdown_all()
        except Exception as e:
            print(f"[InputService] wine_input_bridge shutdown error: {e}")
        self._drain_focused_passthrough()
        if self._xlib:
            self._xlib.disconnect()
            self._xlib = None



    # ── Keymap helpers ─────────────────────────────────────────────────────

    def _movement_keys(self) -> frozenset:
        """Keys (across all sets) that classify as routable actions for the
        keydown dispatcher's `is_movement` gate.

        Scoped to the FOREGROUND game's key universe, NOT a cross-game union: a
        physical key must be interpreted through the game the user is actually
        playing. Otherwise a key bound only in the other game leaks in -- e.g.
        CC's book=Escape made Escape count as movement in a TTR session, which
        shadowed the `elif key == "Escape":` chat-close branch and stranded the
        background toon (chat stuck open) until a service refresh.

        When the foreground game is not yet known there is no coherent action
        namespace, so classify nothing (the literal Return/Escape/BackSpace
        branches still handle those keys); we deliberately do NOT fall back to
        the cross-game union, which would reintroduce the collision. The legacy
        no-keymap-manager path keeps the hard-coded MOVEMENT_KEYS."""
        if self.keymap_manager is None:
            return MOVEMENT_KEYS
        game = self._foreground_game()
        if game is None:
            return frozenset()
        return self.keymap_manager.get_keys_for_game(game)

    def _get_assignments(self, enabled) -> list:
        """Return per-toon set indices."""
        if self.get_keymap_assignments:
            return self.get_keymap_assignments()
        return [0] * len(enabled)

    def _strict_ttr_enabled(self) -> bool:
        """Whether the strict-separation toggle is ON for TTR. Default ON;
        the toggle is the escape hatch back to focus-passthrough behavior.
        This reflects ONLY the user setting, not whether the grabber is armed."""
        if self.settings_manager is None:
            return True
        return bool(self.settings_manager.get(STRICT_TTR_SEPARATION, True))

    def _strict_ttr_active(self) -> bool:
        """Whether strict separation can actually be enforced for the focused
        TTR window right now: the toggle is ON AND grabs are currently INSTALLED
        for it (`_ttr_grabs_active`). Mere existence of a grabber object is not
        enough -- the focus handler uninstalls grabs for non-game focus and for
        non-preset/custom sets, and in that state the focused window's physical
        key is NOT suppressed. If the router synthesized then, it would move the
        focused toon both natively (unsuppressed key) and via the synth -> a
        double-move. So the gate must reflect ACTUAL suppression, not object
        existence. When grabs are not installed, strict separation degrades to
        today's unconditional focused-window skip.

        Supported on Linux/X11, Windows, and macOS (`_ttr_strict_supported`);
        other platforms keep pre-feature behavior. Also requires a usable delivery
        backend (`_delivery_backend_ready`) so suppression never outlives the
        ability to re-synthesize (which would freeze the focused toon). The
        `_key_grabber is not None` check is a safety net against a stale flag
        after teardown."""
        return (
            self._strict_ttr_enabled()
            and self._ttr_strict_supported()
            and self._key_grabber is not None
            and self._ttr_grabs_active
            and self._delivery_backend_ready()
            and self._focused_strict_delivery_safe()
        )

    def _focused_native_key_suppressed(self, key) -> bool:
        """Whether the grabber actually WITHHELD `key` from the focused window's
        native delivery, so re-synthesizing it to the focused toon is correct
        (the synth is the only delivery) rather than a double.

        A full-grab grabber (X11, needs_focused_passthrough=True) redirects ALL
        keyboard events, so every key is withheld. A NON-EXCLUSIVE grab
        (macOS/Win32, needs_focused_passthrough=False) withholds only the keys it
        actively suppresses; action keys that map to a logical action but are not
        in the suppressed movement set (jump=space, tasks=t) reach the focused
        window natively and must NOT be re-synthesized. should_suppress() is the
        same predicate the OS hook uses to decide native suppression, so it is the
        authoritative per-key truth. Defaults to True (pre-fix synth behavior) for
        a missing grabber/predicate so this never strands the focused toon."""
        grabber = self._key_grabber
        if grabber is None:
            return True
        if getattr(grabber, "needs_focused_passthrough", True):
            return True
        should_suppress = getattr(grabber, "should_suppress", None)
        if should_suppress is None:
            return True
        try:
            return bool(should_suppress(key))
        except Exception:
            return True

    def _capability_for(self, win_id):
        """UIPI delivery capability for a window id, via the injected provider.
        Never raises; never coerces win_id (the provider owns conversion)."""
        from utils.win32_integrity import Capability
        try:
            return self._capability_provider(win_id)
        except Exception:
            return Capability.UNKNOWN

    def _focused_strict_delivery_safe(self) -> bool:
        """True when arming strict TTR suppression for the FOCUSED window is safe:
        either the focused window is not a TTR game window, or its UIPI capability
        is OK. BLOCKED_UIPI/UNKNOWN -> unsafe (fail closed): never suppress native
        input we cannot redeliver."""
        from utils.win32_integrity import Capability
        try:
            active = self.window_manager.get_active_window()
        except Exception:
            return True
        if not active:
            return True
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(str(active))
        except Exception:
            return True
        if game != "ttr":
            return True
        return self._capability_for(active) is Capability.OK

    def _refresh_uipi_capabilities(self) -> None:
        """Refresh the UIPI capability of EVERY managed game window via the cache's
        get() (which does the OpenProcess token read). Runs OFF the input hot path
        (focus change, window-assignment change, periodic timer) so the hot path
        only ever peeks. No-op when there is no cache (injected provider in tests,
        or off Windows where the feature is inert)."""
        if self._capability_cache is None:
            return
        try:
            ids = list(self.window_manager.get_window_ids())
        except Exception:
            return
        for w in ids:
            try:
                self._capability_cache.get(int(w))
            except Exception:
                pass

    def _start_uipi_refresh(self) -> None:
        """Wire the off-hot-path UIPI capability refresh: on window-assignment
        change (window_ids_updated) and on a periodic timer (the cache TTL). No-op
        when there is no cache (off Windows / injected provider in tests)."""
        if self._capability_cache is None:
            return
        if not self._uipi_refresh_wired:
            try:
                self.window_manager.window_ids_updated.connect(
                    self._on_window_ids_updated_refresh)
                self._uipi_refresh_wired = True
            except Exception as e:  # noqa: BLE001
                print(f"[InputService] uipi window_ids_updated connect failed: {e}")
        try:
            from PySide6.QtCore import QTimer
            from utils.win32_integrity import CAPABILITY_TTL_SECONDS
            if self._uipi_refresh_timer is None:
                self._uipi_refresh_timer = QTimer(self)
                self._uipi_refresh_timer.setInterval(int(CAPABILITY_TTL_SECONDS * 1000))
                self._uipi_refresh_timer.timeout.connect(self._refresh_uipi_capabilities)
            self._uipi_refresh_timer.start()
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] uipi refresh timer start failed: {e}")

    def _on_window_ids_updated_refresh(self, *args) -> None:
        self._refresh_uipi_capabilities()

    def _stop_uipi_refresh(self) -> None:
        t = self._uipi_refresh_timer
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass

    def _ttr_strict_supported(self) -> bool:
        """TTR strict separation is implemented for Linux/X11, Windows, and
        macOS. Any other platform stays unsupported. This is the single
        platform-capability gate."""
        import sys
        return sys.platform in ("linux", "win32", "darwin")

    def _delivery_backend_ready(self) -> bool:
        """Whether _send_via_backend can ACTUALLY deliver synthetic input right
        now. Mirrors _send_via_backend's delivery capability exactly so strict
        separation never suppresses native movement while delivery is dead (which
        would freeze the focused toon). When not ready, strict degrades to native
        delivery (the toon still moves)."""
        import sys
        if self._xlib is not None:
            # On darwin a connected backend is NOT sufficient: CGEventPostToPid
            # silently no-ops without Accessibility (TCC), which is revocable at
            # runtime. If posting permission is gone, reporting ready would let
            # strict suppression eat native movement while delivery fails ->
            # frozen focused toon. Require live post-permission so suppression
            # instead degrades to native delivery.
            if sys.platform == "darwin":
                check = getattr(self._xlib, "has_post_access", None)
                if check is not None and not check():
                    return False
            return True                       # XlibBackend / Win32Backend / MacOSBackend connected
        if self._xlib_backend_failed:
            return False                      # requested backend failed -> events dropped
        return sys.platform == "linux"        # _xlib None, not failed: only Linux has the explicit-xdotool delivery path

    # ── Keymap-aware send methods ──────────────────────────────────────────

    def _send_logical_action_km(self, action, key, enabled, assignments,
                                only_windows=None, skip_windows=None):
        """Route a movement-class action to toons.

        only_windows / skip_windows (optional sets of window ids) restrict
        delivery — generic filters kept for FSM-mode callers that need to
        split focused vs background delivery (e.g. a future
        re-synth-on-flip for in-flight suppressed keys).

        Strict per-toon routing: each toon responds only to keys that its
        own assigned set binds. No cross-game broadcast fallback.

        CC: each enabled toon's assigned set is consulted independently for
        the pressed key. When a toon's set binds the key, TTMT emits CC's
        canonical key for that action to that toon's window. For movement,
        canonical is the WASD that TTMT locks CC's prefs to
        (utils/cc_isolation.py). For other actions, canonical is CC's
        default (set 0) binding.

        The foreground toon is skipped only when the pressed key already
        matches the canonical -- in that case the OS-delivered key reaches
        the focused window naturally. When the pressed key differs from the
        canonical (e.g. user pressed Up but CC's prefs lock means Up is
        ignored), the foreground also gets a bridge-sent canonical key.

        TTR (and any future non-CC game): same strict per-toon rule. The
        set is an input-translation layer only; outbound is always the
        game's default (set 0) binding so the bg toon's settings.json
        (the user's native customization) is honored.

        Returns the list of (window_id, keysym) pairs actually delivered, so
        keydown callers can record them on the hold (HeldKey.sends) and the
        keyup can release exactly what the keydown pressed.
        """
        sent: list[tuple[str, str]] = []
        # _fsm_draining: the FSM applies its capture transition BEFORE the
        # entry drain runs (the pure module cannot defer its own state), so
        # the drain's keyups — for keydowns that WERE dispatched pre-capture —
        # must bypass this gate. FSM-only; the legacy paths drain before the
        # flag flips (chat-open) or intentionally skip keyups (release_all
        # while chat active) and are unaffected.
        if self.global_chat_active and not self._fsm_draining:
            return sent
        if self.keymap_manager is None:
            return sent

        from utils.game_registry import GameRegistry
        from utils import logical_actions, cc_isolation

        cc_canonical_movement = cc_isolation.canonical_to_ttmt_keysyms(
            cc_isolation.DEFAULT_CANONICAL
        )

        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        registry = GameRegistry.instance()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if only_windows is not None and win not in only_windows:
                continue
            if skip_windows is not None and win in skip_windows:
                continue
            toon_game = registry.get_game_for_window(str(win))
            if toon_game is None:
                toon_game = "ttr"  # Windows fallback: TTMT pre-dates CC support and TTR is the safe default
            set_idx = assignments[i] if i < len(assignments) else 0

            if toon_game == "cc":
                toon_action = self.keymap_manager.get_action_in_set("cc", set_idx, key)
                if toon_action is None and set_idx != 0:
                    # The toon is on a non-default set that does not bind this
                    # key. Fall back to the default set's binding -- but ONLY
                    # when the resolved action is non-movement AND this toon's
                    # set leaves that action unbound. Movement actions stay
                    # strict per-toon (a key the set does not bind for movement
                    # is not forwarded as movement). A non-movement action that
                    # the set REBINDS to its own key must not be triggered by
                    # its default key either, or it cross-fires across toons;
                    # the get_key_for_action falsy check gates the fallback to
                    # the missing/empty case.
                    default_action = self.keymap_manager.get_action_in_set("cc", 0, key)
                    if default_action is not None and default_action not in _MOVEMENT_ACTIONS \
                            and not self.keymap_manager.get_key_for_action("cc", set_idx, default_action):
                        toon_action = default_action
                if toon_action is None:
                    continue
                if not logical_actions.supports("cc", toon_action):
                    continue
                canonical = cc_canonical_movement.get(toon_action)
                if canonical is None:
                    canonical = self.keymap_manager.get_key_for_action("cc", 0, toon_action)
                if canonical is None:
                    continue
                if win == active_window and key == canonical:
                    continue
                keysym = self._resolve_keysym(canonical)
                if keysym:
                    self._send_via_backend(action, win, keysym)
                    sent.append((win, keysym))
                    if self.logging_enabled and action == "keydown" and key != canonical:
                        self.input_log.emit(
                            f"[Input] '{key}' -> '{canonical}' "
                            f"(cc action: {toon_action}, set {set_idx + 1})"
                        )
            else:
                # Strict per-toon for movement; default-set fallback for
                # non-movement actions ONLY when this toon's set leaves the
                # action unbound. A set may rebind any non-movement action
                # (jump, book, etc.) to its own key; when it does, the
                # action's default key is no longer this toon's trigger, so
                # forwarding it would cross-fire (e.g. Toon1 jump=space
                # leaking into a toon whose set rebinds jump to Control_R).
                # The fallback therefore inherits the default binding only
                # when get_key_for_action is falsy (action missing/empty in
                # this set). Outbound stays sourced from set 0 (native binding).
                toon_action = self.keymap_manager.get_action_in_set(toon_game, set_idx, key)
                if toon_action is None and set_idx != 0:
                    default_action = self.keymap_manager.get_action_in_set(toon_game, 0, key)
                    if default_action is not None and default_action not in _MOVEMENT_ACTIONS \
                            and not self.keymap_manager.get_key_for_action(toon_game, set_idx, default_action):
                        toon_action = default_action
                if toon_action is None:
                    continue
                if not logical_actions.supports(toon_game, toon_action):
                    continue
                outbound = self.keymap_manager.get_key_for_action(toon_game, 0, toon_action)
                if outbound is None:
                    continue
                if win == active_window and not self._strict_drain_active:
                    # The focused window keeps its NATIVE key unless the grabber
                    # actually withheld it; re-synthesizing a key it received
                    # natively double-delivers (the macOS/Win32 "space/t double,
                    # wasd don't" bug). Skip the focused-toon synth when strict is
                    # not enforceable (toggle OFF or grabs not installed) OR this
                    # specific key was not suppressed. A full-grab grabber (X11)
                    # withholds every key, so its synth stays unconditional; a
                    # non-exclusive grab (macOS/Win32) withholds only the keys it
                    # suppresses, so action keys like jump/space reach the focused
                    # window natively and must not be re-synthesized.
                    # _strict_drain_active bypasses this skip during an explicit
                    # synchronous drain on toggle-off / capture-open, so the
                    # focused toon's synthesized keydown is paired with a keyup.
                    if not self._strict_ttr_active() \
                            or not self._focused_native_key_suppressed(key):
                        continue
                keysym = self._resolve_keysym(outbound)
                if keysym:
                    self._send_via_backend(action, win, keysym)
                    sent.append((win, keysym))
                    if action == "keydown" and win != active_window:
                        self._note_blocked_movement(win, toon_action, key)
                    if self.logging_enabled and action == "keydown" and key != outbound:
                        self.input_log.emit(
                            f"[Input] '{key}' -> '{outbound}' "
                            f"(action: {toon_action}, {toon_game} set {set_idx + 1})"
                        )
        return sent

    def _dispatch_keyup_for_entry(self, entry, enabled, assignments) -> None:
        """Single-site keyup routing by HoldKind. Used by _dispatch_keyup
        on individual releases and by the drain helpers on bulk drains.
        Extracted so any future change to a kind's dispatch path lands
        in one place."""
        if entry.kind == HoldKind.MODIFIER:
            self._send_modifier_to_bg("keyup", entry.key, enabled, assignments)
        elif entry.kind == HoldKind.MOVEMENT:
            sends = getattr(entry, "sends", None)
            if sends is not None:
                # Release exactly what the keydown delivered. Re-translating
                # the physical key here reads the CURRENT assignments, and a
                # keyset switched mid-hold makes the keyup resolve to nothing
                # — the synthesized keydown is then never released and the
                # toon keeps moving (live darwin float repro: the overlay's
                # nonactivating panel switches keysets with no focus change,
                # so no grab reinstall or cleanup drain intervenes either).
                # Chat gate mirrors _send_logical_action_km: while a capture
                # is active (and this is not the FSM's own entry drain),
                # keydowns were never dispatched, so keyups must not be.
                if not (self.global_chat_active and not self._fsm_draining):
                    for win, keysym in sends:
                        self._send_via_backend("keyup", win, keysym)
            else:
                # No record (hold acquired outside the movement router, e.g.
                # BackSpace's tap path or a phantom-suppressed press): keep
                # the legacy re-translate dispatch.
                self._send_logical_action_km("keyup", entry.key, enabled, assignments)
            self._release_uipi_hold(entry.key)
        elif entry.kind == HoldKind.ACTION:
            self._send_action_keyup_to_bg(entry.key, enabled, assignments)

    def _dispatch_keyup(self, key, enabled, assignments) -> bool:
        """Process a single keyup event.

        Returns True if the released key was BackSpace (so the caller can
        reset BackSpace repeat timing); False otherwise.

        Routes by HoldKind discriminator captured at acquire time, so chat
        state changes between keydown and keyup do not affect dispatch.
        """
        entry = self.holds.release(key)
        if entry is None:
            self.bg_typing_held.discard(key)
            return False
        # MOVEMENT and ACTION log the release; MODIFIER does not (matches
        # pre-refactor behavior).
        if entry.kind in (HoldKind.MOVEMENT, HoldKind.ACTION):
            self._log_key(key, "released")
        self._dispatch_keyup_for_entry(entry, enabled, assignments)
        return key == "BackSpace" and entry.kind == HoldKind.MOVEMENT

    def _send_modifier_to_bg(self, action, key, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win != active_window:
                self._send_via_backend(action, win, keysym)

    def _send_action_keydown_to_bg(self, key, enabled, assignments):
        """Send a sustained keydown for a non-movement action key to bg toons."""
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win != active_window:
                self._send_via_backend("keydown", win, keysym)

    def _send_action_keyup_to_bg(self, key, enabled, assignments):
        """Send a keyup matching a previously-sent action keydown to bg toons."""
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win != active_window:
                self._send_via_backend("keyup", win, keysym)

    def _drain_kind(self, kind, enabled, assignments):
        """Drain held keys of one kind, dispatching keyup via that kind's
        send path. Used when the caller wants to clear only one bucket
        (e.g. chat-opens path wants to clear ACTION but keep modifiers
        and movement). Drain paths intentionally skip per-key logging;
        callers log the regime change instead."""
        for key in list(self.holds.keys_by_kind(kind)):
            entry = self.holds.release(key)
            if entry is None:
                continue
            self._dispatch_keyup_for_entry(entry, enabled, assignments)

    def _drain_all_held(self, enabled, assignments):
        """Drain every held key across all kinds, dispatching keyup via
        each kind's send path. Used on focus loss and shutdown. Drain
        paths intentionally skip per-key logging; callers log the regime
        change instead."""
        for entry in self.holds.drain():
            self._dispatch_keyup_for_entry(entry, enabled, assignments)

    def _send_typing_to_bg(self, key, enabled, assignments, movement_keys=None):
        from utils.game_registry import GameRegistry
        from utils import logical_actions

        active_window = self.window_manager.get_active_window()
        if movement_keys is None:
            movement_keys = self._movement_keys()
        window_ids = self.window_manager.get_window_ids()
        registry = GameRegistry.instance()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win == active_window:
                continue

            toon_game = registry.get_game_for_window(str(win))
            set_idx = assignments[i] if i < len(assignments) else 0

            if self.keymap_manager and toon_game is not None:
                is_toon_movement_key = (
                    self.keymap_manager.get_action_in_set(toon_game, set_idx, key) is not None
                )
                # Movement-class keys ride the keydown path in _send_logical_action_km,
                # which produces native typed input in Panda3D chat anyway.
                if is_toon_movement_key and not self.global_chat_active:
                    continue

            if self.global_chat_active and not self._is_chat_allowed(i):
                continue
            if key in self.get_chat_block_list() and not self._is_chat_allowed(i):
                continue

            keysym = self._resolve_keysym(key)
            if not keysym:
                continue
            mods = self._active_modifiers()
            self._send_via_backend("key", win, keysym, mods if mods else None)

    def _send_backspace_to_background(self, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win == active_window:
                continue
            if not self._is_chat_allowed(i):
                # Backspace follows the same per-toon chat permission as the
                # typed-character path (_send_typing_to_bg). In focused_only the
                # effective list is all-False, so no background toon gets a
                # chat-editing key; a chat-blocked toon in any mode is likewise
                # skipped. Runs whenever Backspace is held, not only during
                # detected chat.
                continue
            self._send_via_backend("key", win, "BackSpace")

    # ── Chat gate FSM integration (TTMT_CHAT_FSM=1) ────────────────────────
    # The FSM (services/chat_fsm.py) is pure; these helpers execute its
    # decisions/transitions through the existing side-effect helpers so the
    # pinned contracts hold: drain-then-ungrab on capture entry, reinstall at
    # GRACE entry, close-key mirroring scoped to the boxes WE opened.

    def _fsm_ctx(self, movement_keys, full: bool = True) -> ChatCtx:
        """Per-event context. full=False (ticks/keyups, ~200Hz) skips the
        settings.json-backed chord/mode lookups the classifier only needs on
        keydowns — on_tick/on_keyup read bound_keys alone."""
        if not full:
            return ChatCtx(bound_keys=movement_keys)
        game = self._foreground_game()
        chords = ChatCtx.__dataclass_fields__["open_chords"].default
        mode_b = False
        if game == "ttr":
            if self.get_chat_open_chords is not None:
                try:
                    resolved = tuple(self.get_chat_open_chords() or ())
                    if resolved:
                        chords = resolved
                except Exception:
                    pass
            try:
                mode_b = "a" in self.get_chat_block_list()
            except Exception:
                mode_b = False
        return ChatCtx(bound_keys=movement_keys, open_chords=chords, mode_b=mode_b)

    def _fsm_apply_transitions(self, transitions, enabled, assignments,
                               pressed_key=None) -> None:
        _capture_states = (ChatState.CAPTURE, ChatState.CAPTURE_SOFT)
        for tr in transitions:
            if _ITRACE:
                _itrace("fsm", f"{tr.old.name}->{tr.new.name} cause={tr.cause}")
            entering = tr.new in _capture_states and tr.old not in _capture_states
            leaving = tr.old in _capture_states and tr.new not in _capture_states
            if entering:
                # Pinned order: drain ALL held keys (movement, action AND
                # modifier holds — a held W at chat-open must stop the bg
                # toons), THEN ungrab so typing lands natively. The FSM state
                # already reads as captured here, so _fsm_draining lets the
                # drain keyups pass the routing gate.
                try:
                    self._strict_drain_active = True
                    self._fsm_draining = True
                    self._drain_all_held(enabled, assignments)
                except Exception as e:  # noqa: BLE001
                    print(f"[InputService] fsm capture-entry drain failed: {e}")
                finally:
                    self._fsm_draining = False
                    self._strict_drain_active = False
                self.chat_state_changed.emit(True)
                self._resync_grabs_for_input_capture(True)
            elif leaving:
                # Close the boxes WE opened: the pressed chord/Escape for
                # user closes, Escape for ttl/demote/focus/force.
                close_key = (pressed_key
                             if tr.cause in ("send", "close_empty", "escape")
                             and pressed_key is not None else "Escape")
                self._fsm_close_bg_chat(close_key)
                self.chat_state_changed.emit(False)
                self._resync_grabs_for_input_capture(False)

    def _fsm_close_bg_chat(self, key: str) -> None:
        """Orphan guard: a mirrored bg chat box must never outlive the
        capture that opened it."""
        for win in list(self._bg_chat_open):
            try:
                self._send_via_backend("key", win, key)
            except Exception as e:  # noqa: BLE001
                print(f"[InputService] fsm bg-chat close to {win} failed: {e}")
        self._bg_chat_open.clear()

    def _fsm_mirror_open(self, open_key, enabled, assignments, movement_keys,
                         window_ids) -> None:
        """Mirror the open chord (or Mode B letter) to chat-allowed bg toons
        and record their window ids — the scope for every later close."""
        active = self.window_manager.get_active_window()
        recipients = []
        for i, is_en in enumerate(enabled):
            if not is_en or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win == active:
                continue
            if self._is_chat_allowed(i):
                recipients.append(win)
        if not recipients:
            return
        self._send_typing_to_bg(open_key, enabled, assignments, movement_keys)
        self._bg_chat_open.update(str(w) for w in recipients)

    def _fsm_handle_keydown(self, key, now, enabled, assignments,
                            movement_keys, window_ids):
        """FSM-mode keydown dispatch. Returns the decision (None for an OS
        autorepeat, which must not reset hold-duration tracking)."""
        if key in self._fsm_seen_down:
            return None
        self._fsm_seen_down.add(key)
        ctx = self._fsm_ctx(movement_keys)
        dec = self._chat_fsm.on_keydown(key, now, ctx)
        if dec.transitions:
            self._fsm_apply_transitions(dec.transitions, enabled, assignments,
                                        pressed_key=key)
        if _ITRACE and dec.kind in (KeyClass.CHORD_OPEN, KeyClass.CHORD_SEND,
                                    KeyClass.CHORD_CLOSE, KeyClass.ESCAPE_CLEAR):
            _itrace("fsm", f"key={key} verdict={dec.kind.name} "
                           f"state={self._chat_fsm.state.name}")

        # Focused passthrough parity with the legacy dispatcher: every key
        # except BackSpace (its own branch) and movement-as-movement (the
        # router delivers focused).
        if key != "BackSpace" and dec.kind is not KeyClass.MOVEMENT:
            self._send_passthrough_to_focused(key)

        if dec.kind is KeyClass.MODIFIER:
            if self.holds.acquire(key, HoldKind.MODIFIER, now):
                self._send_modifier_to_bg("keydown", key, enabled, assignments)
        elif dec.kind is KeyClass.MOVEMENT:
            if self.holds.acquire(key, HoldKind.MOVEMENT, now):
                if self.logging_enabled:
                    logical = self._resolve_logical_action(key)
                    extra = f" (action: {logical})" if logical else ""
                    self._log_key(key, "pressed", extra)
                sent = self._send_logical_action_km(
                    "keydown", key, enabled, assignments)
                self.holds.record_sends(key, sent)
        elif dec.kind is KeyClass.TYPING:
            if key not in self.bg_typing_held:
                self.bg_typing_held.add(key)
                self._send_typing_to_bg(key, enabled, assignments, movement_keys)
        elif dec.kind is KeyClass.EDIT:
            # BackSpace: sends here, repeat timing stays in the run loop.
            if self.holds.acquire(key, HoldKind.MOVEMENT, now):
                self._log_key(key, "pressed")
                self._send_backspace_to_background(enabled, assignments)
                self._send_backspace_to_focused()
        elif dec.kind is KeyClass.CHORD_OPEN:
            self._log_key(key, "pressed")
            self._fsm_mirror_open(dec.open_key or key, enabled, assignments,
                                  movement_keys, window_ids)
        elif dec.kind is KeyClass.SUPPRESS:
            if key not in self.bg_typing_held:
                self.bg_typing_held.add(key)
        else:
            # CHORD_SEND / CHORD_CLOSE / ESCAPE_CLEAR: terminal — never fall
            # through to typing or ACTION broadcast (an unbound Escape must
            # not reach _send_action_keydown_to_bg). CHORD_CLOSE mirroring
            # already ran in the transition applier. ACTION handled here:
            if dec.kind is KeyClass.ACTION:
                if self.holds.acquire(key, HoldKind.ACTION, now):
                    self._log_key(key, "pressed")
                    self._send_action_keydown_to_bg(key, enabled, assignments)
            elif key not in self.bg_typing_held:
                self.bg_typing_held.add(key)
        return dec

    def _fsm_handle_keyup(self, key, event_t, enabled, assignments,
                          movement_keys) -> None:
        """Evidence bookkeeping for a flushed keyup. event_t is the
        pending_keyups buffered_at time so tap measurements avoid the flush
        skew. The actual keyup routing stays with _dispatch_keyup."""
        self._fsm_seen_down.discard(key)
        ctx = self._fsm_ctx(movement_keys, full=False)
        res = self._chat_fsm.on_keyup(key, event_t, ctx)
        if res.transitions:
            self._fsm_apply_transitions(res.transitions, enabled, assignments)

    def _fsm_tick(self, now, enabled, assignments, movement_keys) -> None:
        ctx = self._fsm_ctx(movement_keys, full=False)
        res = self._chat_fsm.on_tick(now, ctx)
        if res.transitions:
            self._fsm_apply_transitions(res.transitions, enabled, assignments)

    def _fsm_route_cleanup(self) -> None:
        """Cleanup-branch / release_all_keys hook: force ROUTE and run the
        orphan guard. Idempotent and allocation-free when already ROUTE
        (the cleanup branch runs at ~100Hz)."""
        if not self._fsm_enabled:
            return
        trs = self._chat_fsm.force_route(time.monotonic())
        if trs:
            if _ITRACE:
                _itrace("fsm", f"force_route from {trs[0].old.name}")
            self._fsm_close_bg_chat("Escape")
            self.chat_state_changed.emit(False)
        self._fsm_seen_down.clear()

    def _fsm_handle_focus_change(self, window_id) -> None:
        """Managed-focus-switch-mid-capture guard (see call site)."""
        if not self._fsm_enabled:
            return
        try:
            from utils.game_registry import GameRegistry
            wid = str(window_id) if window_id else None
            is_game = bool(wid) and GameRegistry.instance().get_game_for_window(wid) is not None
        except Exception:
            return
        prev = self._fsm_prev_game_window
        if is_game and prev and wid != prev and self._chat_fsm.in_capture:
            trs = self._chat_fsm.on_focus_change_managed(time.monotonic())
            if trs:
                if _ITRACE:
                    _itrace("fsm", f"focus-switch mid-capture: escape prev={prev}")
                try:
                    self._send_via_backend("key", prev, "Escape")
                except Exception as e:  # noqa: BLE001
                    print(f"[InputService] fsm focus-switch escape failed: {e}")
                enabled = self.get_enabled_toons()
                self._fsm_apply_transitions(trs, enabled,
                                            self._get_assignments(enabled))
        if is_game:
            self._fsm_prev_game_window = wid

    def keep_alive_skip_window(self, win_id) -> bool:
        """Keep-alive must not type its key into an open chat box: skip the
        focused window during any capture, and any bg box we mirrored open.
        Fail-open by construction — no capture, no skips."""
        try:
            wid = str(win_id)
            if wid in self._bg_chat_open:
                return True
            if self.global_chat_active or self._phantom_active:
                active = self.window_manager.get_active_window()
                return active is not None and str(active) == wid
        except Exception:
            return False
        return False

    # ── Run loop ───────────────────────────────────────────────────────────

    def run(self):
        self._apply_backend_setting()
        event_queue    = self.get_event_queue()
        bs_press_time  = None
        bs_last_repeat = 0.0
        pending_keyups: dict[str, float] = {}
        cleanup_was_active = False  # edge-trigger for cleanup-branch trace

        if self._fsm_enabled:
            # Fresh service run starts from ROUTE (a restart must never
            # resurrect a stale capture), and the startup stamp is the
            # running-code proof: live validation BEGINS by confirming it.
            self._chat_fsm.force_route(time.monotonic())
            self._fsm_seen_down.clear()
            self._bg_chat_open.clear()
            try:
                _ctx = self._fsm_ctx(frozenset())
                stamp = (f"[chat] ChatFSM ACTIVE v1 open_chords={_ctx.open_chords} "
                         f"mode_b={_ctx.mode_b}")
            except Exception:
                stamp = "[chat] ChatFSM ACTIVE v1"
            _itrace("chat", stamp)
            self.input_log.emit(stamp)

        try:
            while self.running:
                if not self.should_send_input():
                    # Edge-triggered entry log only (this branch runs ~100Hz; never
                    # log per-iteration). Captures cached vs real X11 focus + the
                    # chat/intent/phantom state at the instant focus leaves.
                    if _ITRACE and not cleanup_was_active:
                        cached = self.window_manager.get_active_window()
                        try:
                            from utils import x11_discovery
                            real = x11_discovery.get_active_window_id()
                        except Exception:
                            real = "?"
                        _itrace("cleanup", f"ENTER cached_active={cached} real_active={real} "
                                f"qsize={event_queue.qsize()} chat={self.global_chat_active} "
                                f"intent={self._intended_ttr_strict} phantom={self._phantom_active}")
                    cleanup_was_active = True
                    drained = []
                    while not event_queue.empty():
                        try:
                            item = event_queue.get_nowait()
                            if _ITRACE:
                                drained.append(item)
                        except queue.Empty:
                            break
                    if _ITRACE and drained:
                        _itrace("cleanup", f"discarded {len(drained)} queued events: {drained}")
                    if len(self.holds) > 0:
                        enabled     = self.get_enabled_toons()
                        assignments = self._get_assignments(enabled)
                        self._drain_all_held(enabled, assignments)
                    self.bg_typing_held.clear()
                    self._drain_focused_passthrough()
                    pending_keyups.clear()
                    if self._fsm_enabled:
                        # Owns the reset (incl. orphan guard) and stays
                        # allocation-free at this ~100Hz call rate; the
                        # legacy resets below would only re-spam the GATED
                        # resync trace every iteration.
                        self._fsm_route_cleanup()
                    else:
                        self._phantom_reset()
                        if self.global_chat_active:
                            self._set_chat_active(False, cause="cleanup")
                            self.chat_active.clear()
                    bs_press_time  = None
                    bs_last_repeat = 0.0
                    self._stop_event.wait(0.01)
                    continue

                if _ITRACE and cleanup_was_active:
                    _itrace("cleanup", f"EXIT (should_send_input True) "
                            f"active={self.window_manager.get_active_window()} "
                            f"chat={self.global_chat_active} intent={self._intended_ttr_strict}")
                cleanup_was_active = False

                now            = time.monotonic()
                enabled        = self.get_enabled_toons()
                assignments    = self._get_assignments(enabled)
                movement_keys  = self._movement_keys()

                if not self._fsm_enabled:
                    # Legacy-only maintenance. The FSM owns its own TTL (and
                    # movement never refreshes it) via _fsm_tick below.

                    # Idle timeout — reset chat state if no typing for 15s
                    if (self.global_chat_active or self._phantom_active) and self._chat_last_activity > 0:
                        if now - self._chat_last_activity > self.CHAT_IDLE_TIMEOUT:
                            self._timeout_reset_chat(enabled, assignments)

                    # Phantom gate — clear stale phantom state if the gate has
                    # closed since activation (e.g. user toggled chat off on the
                    # last chat-enabled bg toon while phantom was suppressing).
                    if self._phantom_active and not self._phantom_gate_open():
                        self._phantom_reset()

                window_ids = self.window_manager.get_window_ids()
                if not window_ids:
                    self.window_manager.assign_windows()
                    window_ids = self.window_manager.get_window_ids()

                while not event_queue.empty():
                    try:
                        action, key = event_queue.get_nowait()
                    except queue.Empty:
                        break

                    # Auto-repeat dedup: pynput delivers X11 auto-repeat as
                    # KeyRelease+KeyPress pairs (XKB DetectableAutoRepeat is
                    # off by default). Buffer each keyup; if a matching keydown
                    # arrives within AUTO_REPEAT_DEDUP_WINDOW, drop both halves
                    # (the key is still logically held). If no matching keydown
                    # arrives in time, flush the keyup as a real release in the
                    # post-drain block below. The grabber does this for grabbed
                    # keys at the X level; this is the equivalent for keys that
                    # reach InputService via pynput.
                    if action == "keydown" and key in pending_keyups:
                        del pending_keyups[key]
                        if _ITRACE and key in ("Return", "Escape"):
                            _itrace("chat", f"keydown {key} DEDUPED (treated as autorepeat)")
                        continue
                    if action == "keyup":
                        pending_keyups[key] = now
                        continue

                    if action == "keydown":

                        if self._fsm_enabled:
                            dec = self._fsm_handle_keydown(
                                key, now, enabled, assignments,
                                movement_keys, window_ids)
                            if (dec is not None and key == "BackSpace"
                                    and dec.kind is KeyClass.EDIT):
                                bs_press_time  = now
                                bs_last_repeat = 0.0
                            continue

                        # When keymap is active, movement keys take priority over
                        # modifiers — e.g. Control_L as jump, Alt_L as book.
                        # BUT when chat is active, modifier keys (e.g. Shift_L mapped
                        # to "map") must act as modifiers so shifted typing works.
                        is_movement = key in movement_keys
                        is_modifier = key in MODIFIER_KEYS and (
                            not is_movement or self.global_chat_active or self._phantom_active
                        )
                        if is_modifier:
                            is_movement = False

                        # Focused-toon passthrough: deliver every key to the
                        # focused TTR window via the reliable pynput path, EXCEPT
                        # (a) the movement-as-movement case _send_logical_action_km
                        # already delivers, and (b) BackSpace (handled as key-taps
                        # with repeat in its own branch). Verbatim; gated inside
                        # the helper so it no-ops when strict is off.
                        if key != "BackSpace" and not (
                            is_movement and not self.global_chat_active
                            and not self._phantom_active
                        ):
                            self._send_passthrough_to_focused(key)

                        if is_modifier:
                            if self.holds.acquire(key, HoldKind.MODIFIER, now):
                                self._send_modifier_to_bg("keydown", key, enabled, assignments)

                        elif is_movement:
                            if self.holds.acquire(key, HoldKind.MOVEMENT, now):
                                if self.logging_enabled:
                                    logical = self._resolve_logical_action(key)
                                    extra = f" (action: {logical})" if logical else ""
                                    self._log_key(key, "pressed", extra)
                                if _ITRACE:
                                    _route = ("phantom-suppress" if self._phantom_active
                                              else "typing-broadcast" if self.global_chat_active
                                              else "movement-route")
                                    _itrace("movement", f"keydown key={key} route={_route} "
                                            f"active={self.window_manager.get_active_window()} "
                                            f"chat={self.global_chat_active} phantom={self._phantom_active} "
                                            f"strict_active={self._strict_ttr_active()}")
                                if self._phantom_active:
                                    # Stealth chat — suppress movement to bg toons
                                    self._chat_last_activity = now
                                else:
                                    sent = self._send_logical_action_km(
                                        "keydown", key, enabled, assignments)
                                    self.holds.record_sends(key, sent)
                                    # When global chat is active, movement keys (including space)
                                    # are suppressed natively, so we must broadcast them via typing.
                                    if self.global_chat_active:
                                        self._chat_last_activity = now
                                        self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                        elif key == "BackSpace":
                            if self.holds.acquire(key, HoldKind.MOVEMENT, now):
                                self._log_key(key, "pressed")
                                bs_press_time  = now
                                bs_last_repeat = 0.0
                                if self._phantom_active:
                                    self._chat_last_activity = now
                                else:
                                    self._send_backspace_to_background(enabled, assignments)
                                    self._send_backspace_to_focused()

                        elif key == "Return":
                            if key not in self.bg_typing_held:
                                self.bg_typing_held.add(key)
                                self._log_key(key, "pressed")
                                if _ITRACE:
                                    _itrace("chat", f"Return dispatch phantom={self._phantom_active} "
                                                    f"chat={self.global_chat_active}")
                                if self._phantom_active:
                                    # Whisper send detected — don't toggle chat on bg toons
                                    self._phantom_reset()
                                else:
                                    self._set_chat_active(not self.global_chat_active, cause="return")
                                    self._chat_last_activity = now if self.global_chat_active else 0.0
                                    if self.global_chat_active:
                                        # Chat just opened. Release any in-game keys the user
                                        # is still holding so they do not stick on bg toons.
                                        self._drain_kind(HoldKind.ACTION, enabled, assignments)
                                    for i in range(min(len(assignments), len(enabled))):
                                        if i < len(window_ids) and enabled[i]:
                                            if not self._is_chat_allowed(i):
                                                pass
                                            elif i in self.chat_active:
                                                self.chat_active.discard(i)
                                            else:
                                                self.chat_active.add(i)
                                    self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                        elif key == "Escape":
                            if key not in self.bg_typing_held:
                                self.bg_typing_held.add(key)
                                self._log_key(key, "pressed")
                                if _ITRACE:
                                    _itrace("chat", f"Escape dispatch phantom={self._phantom_active} "
                                                    f"chat={self.global_chat_active}")
                                was_chatting = self.global_chat_active
                                self._set_chat_active(False, cause="escape")
                                self.chat_active.clear()
                                self._phantom_reset()
                                if was_chatting:
                                    self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                        else:
                            if self._phantom_active:
                                # Stealth chat — suppress forwarding (chat is open in spirit)
                                if key not in self.bg_typing_held:
                                    self.bg_typing_held.add(key)
                                    self._chat_last_activity = now
                            elif self.global_chat_active:
                                # Chat open — tap each character through typing path
                                if key not in self.bg_typing_held:
                                    self.bg_typing_held.add(key)
                                    self._chat_last_activity = now
                                    self._send_typing_to_bg(key, enabled, assignments, movement_keys)
                            elif len(key) == 1 and key.isprintable():
                                # Possible whisper reply (3 printable chars with no chat open).
                                # Gated by _phantom_gate_open(): when no chat-enabled bg toon
                                # exists, phantom serves no purpose and is skipped entirely.
                                if key not in self.bg_typing_held:
                                    self.bg_typing_held.add(key)
                                    if self._phantom_gate_open():
                                        self._phantom_char_count += 1
                                        if self._phantom_char_count >= 3:
                                            # NOTE: _phantom_active is set before draining here
                                            # (unlike chat-open, where global_chat_active must
                                            # be False during the drain). Safe because
                                            # _send_logical_action_km has no _phantom_active
                                            # early-return guard; if one is ever added, the
                                            # drain must move above this assignment.
                                            self._phantom_active = True
                                            self._chat_last_activity = now
                                            if self.logging_enabled:
                                                self.input_log.emit("[Input] Whisper reply detected; input suppressed")
                                            # Drain held movement before ungrabs so no toon
                                            # is left walking while whisper mode is active.
                                            try:
                                                self._strict_drain_active = True
                                                self._drain_all_held(enabled, assignments)
                                            except Exception as _e:  # noqa: BLE001
                                                print(f"[InputService] phantom-open drain failed: {_e}")
                                            finally:
                                                self._strict_drain_active = False
                                            self._resync_grabs_for_input_capture(True)
                                        else:
                                            self._send_typing_to_bg(key, enabled, assignments, movement_keys)
                                    else:
                                        self._phantom_char_count = 0
                                        self._send_typing_to_bg(key, enabled, assignments, movement_keys)
                            else:
                                # In-game non-printable key (Delete, F-keys, numpad, etc.)
                                # Hold for as long as the user holds it so TTR's action-key
                                # duration replicates on background toons.
                                if self.holds.acquire(key, HoldKind.ACTION, now):
                                    self._log_key(key, "pressed")
                                    self._send_action_keydown_to_bg(key, enabled, assignments)

                # Flush keyups that have been buffered past the auto-repeat
                # window. These look like real releases — no matching keydown
                # arrived in time — BUT X11 has one more ambiguity the timer
                # can't catch: when two keys are held, only the most-recent one
                # auto-repeats, and releasing the OTHER key ends that repeat with
                # a final, UNPAIRED release. That unpaired release waits out the
                # window and would stop a still-held toon. So before treating a
                # buffered keyup as real, confirm the key is actually physically
                # up. If it is still held (positive XQueryKeymap), it's an
                # auto-repeat artifact — drop it; the genuine release will buffer
                # and flush later. Unknown/non-X paths fall back to time-based.
                for stale_key, buffered_at in list(pending_keyups.items()):
                    if now - buffered_at >= self.AUTO_REPEAT_DEDUP_WINDOW:
                        del pending_keyups[stale_key]
                        _phys = self._key_phys_state(stale_key)
                        if _ITRACE:
                            _itrace("flush", f"keyup key={stale_key} phys={_phys} "
                                             f"-> {'DROP(held)' if _phys is True else 'dispatch'}")
                        if _phys is True:
                            continue
                        if self._fsm_enabled:
                            # Evidence bookkeeping. buffered_at is the event
                            # time (avoids the flush skew on tap
                            # measurements); routing stays with the dispatch
                            # below.
                            self._fsm_handle_keyup(stale_key, buffered_at,
                                                   enabled, assignments,
                                                   movement_keys)
                        self._release_focused_passthrough(stale_key)
                        if self._dispatch_keyup(stale_key, enabled, assignments):
                            bs_press_time  = None
                            bs_last_repeat = 0.0

                if self._fsm_enabled:
                    self._fsm_tick(now, enabled, assignments, movement_keys)

                if bs_press_time is not None and self.holds.contains("BackSpace") and not self._phantom_active:
                    held_for = now - bs_press_time
                    if held_for >= self.BACKSPACE_REPEAT_DELAY:
                        if now - bs_last_repeat >= self.BACKSPACE_REPEAT_INTERVAL:
                            bs_last_repeat = now
                            self._send_backspace_to_background(enabled, assignments)
                            self._send_backspace_to_focused()

                time.sleep(0.005)
        finally:
            self.release_all_keys()

    def should_send_input(self):
        active = self.window_manager.get_active_window()
        if not active:
            return False
        if active in self.window_manager.get_window_ids():
            return True
        multitool_id = self.settings_manager.get("multitool_window_id") if self.settings_manager else None
        return bool(multitool_id and active == str(multitool_id))

    def _foreground_game(self) -> str | None:
        from utils.game_registry import GameRegistry
        wid = self.window_manager.get_active_window()
        game = None
        if wid:
            game = GameRegistry.instance().get_game_for_window(str(wid))
        if game is not None:
            self._last_known_foreground_game = game
        return self._last_known_foreground_game

    def _resolve_logical_action(self, pressed_key: str) -> str | None:
        if self.keymap_manager is None:
            return None
        game = self._foreground_game()
        if game is None:
            return None
        default_set = self.keymap_manager.get_default(game)
        from utils import logical_actions
        for action in logical_actions.actions_for(game):
            if default_set.get(action) == pressed_key:
                return action
        return None

    def _active_modifiers(self):
        seen = set()
        mods = []
        for key in self.holds.keys_by_kind(HoldKind.MODIFIER):
            prefix = MODIFIER_PREFIX.get(key)
            if prefix and prefix not in seen:
                seen.add(prefix)
                mods.append(prefix)
        return mods

    def _is_chat_allowed(self, toon_index):
        if self.get_chat_enabled is None:
            return True
        chat_enabled = self.get_chat_enabled()
        return toon_index < len(chat_enabled) and chat_enabled[toon_index]

    def _is_chat_active(self, toon_index):
        return toon_index in self.chat_active

    def _focused_toon_tag(self):
        active_wid = self.window_manager.get_active_window()
        for i, wid in enumerate(self.window_manager.get_window_ids()):
            if wid == active_wid:
                return f" [Toon {i + 1}]"
        return ""

    def _log_key(self, key, state, extra=""):
        if not self.logging_enabled:
            return
        tag = self._focused_toon_tag()
        self.input_log.emit(f"[Input]{tag} '{key}' {state}{extra}")

    def _resync_grabs_for_input_capture(self, capturing: bool) -> None:
        """A focused TTR window under route_all has its movement keys suppressed
        from native delivery. When the game needs native typing (chat box,
        whisper/stealth), ungrab so keystrokes land; reinstall when it ends.
        Callers MUST drain held movement (with _strict_drain_active set) before
        invoking with capturing=True, so no toon is left walking.
        No-op without a grabber or where TTR strict is unsupported."""
        if (self._key_grabber is None
                or not self._ttr_strict_supported()
                or not self._intended_ttr_strict):
            if _ITRACE:
                _itrace("chat", f"resync capturing={capturing} GATED "
                                f"(grabber={self._key_grabber is not None} "
                                f"supported={self._ttr_strict_supported()} "
                                f"intended_strict={self._intended_ttr_strict})")
            return
        try:
            if capturing:
                if _ITRACE:
                    _itrace("chat", "resync -> uninstall_grabs (capture on)")
                self._key_grabber.uninstall_grabs()
            else:
                seed = self.window_manager.get_active_window()
                if _ITRACE:
                    _itrace("chat", f"resync -> reinstall via focus seed={seed}")
                self._on_active_window_changed_for_grabber(seed or "")
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] capture grab resync failed: {e}")

    def _set_chat_active(self, active: bool, cause: str = ""):
        """Set global_chat_active and emit signal on change."""
        if _ITRACE:
            _itrace("chat", f"set_chat_active({active}) cause={cause or '?'} cur={self.global_chat_active} "
                            f"phantom={self._phantom_active} intended_strict={self._intended_ttr_strict}")
        if self.global_chat_active != active:
            if active:
                try:
                    self._strict_drain_active = True
                    enabled = self.get_enabled_toons()
                    self._drain_all_held(enabled, self._get_assignments(enabled))
                except Exception as e:  # noqa: BLE001
                    print(f"[InputService] chat-open drain failed: {e}")
                finally:
                    self._strict_drain_active = False
            self.global_chat_active = active
            self.chat_state_changed.emit(active)
            if self.logging_enabled:
                self.input_log.emit(f"[Input] Chat broadcast {'activated' if active else 'deactivated'}")
            if active:
                self._resync_grabs_for_input_capture(True)
            elif not self._phantom_active:
                # Don't reinstall grabs while phantom capture is still live.
                # release_all_keys() calls _set_chat_active(False) THEN
                # _phantom_reset(), so phantom hasn't been cleared yet here;
                # _phantom_reset() will reinstall once it clears.
                self._resync_grabs_for_input_capture(False)
            elif _ITRACE:
                _itrace("chat", "set_chat_active(False) skipped resync (phantom active)")

    def _phantom_gate_open(self) -> bool:
        """Return True iff phantom suppression has a purpose given the
        current per-toon chat-enable state.

        Phantom protects bg toons from accidentally receiving whisper-reply
        text. If no enabled bg toon has chat enabled, the protection is moot:
        chat block-list entries (Return, Escape, and letters when TTR has
        chat-by-typing on) are already filtered out by _send_typing_to_bg.

        Foreground toon is excluded because its chat state does not affect
        what gets broadcast to other toons.
        """
        # Hard gate: phantom suppression runs ONLY in the per_toon (manual)
        # mode. In every other mode (focused_only / all_toons / keyset_dynamic)
        # the whisper-reply detector is off regardless of per-toon chat state.
        # get_chat_handling_mode returns canonical values; legacy callers that
        # pass get_chat_handling_mode=None keep the manual-equivalent path so
        # existing test fixtures are unaffected.
        from utils.settings_keys import CHAT_HANDLING_PER_TOON
        if self.get_chat_handling_mode is not None:
            if self.get_chat_handling_mode() != CHAT_HANDLING_PER_TOON:
                return False
        enabled = self.get_enabled_toons()
        if not enabled:
            return False
        chat = self.get_chat_enabled() if self.get_chat_enabled else [True] * len(enabled)
        window_ids = self.window_manager.get_window_ids()
        active_window = self.window_manager.get_active_window()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            if window_ids[i] == active_window:
                continue
            if i < len(chat) and chat[i]:
                return True
        return False

    def _phantom_reset(self):
        """Reset phantom (stealth whisper) detection state."""
        if _ITRACE and self._phantom_active:
            _itrace("chat", "phantom_reset (was active)")
        self._phantom_char_count = 0
        self._phantom_active = False
        self._chat_last_activity = 0.0
        # Reinstall grabs if neither phantom nor chat is active; if chat is
        # still active _set_chat_active(False) will handle the reinstall.
        if not self.global_chat_active:
            self._resync_grabs_for_input_capture(False)

    def _timeout_reset_chat(self, enabled, assignments):
        """Idle timeout fired — send Escape to bg toons to close any open chat, then reset."""
        if self.logging_enabled:
            self.input_log.emit("[Input] Chat idle timeout; resetting chat state")
        # Defensive: in case any action key was somehow held during chat,
        # release it now. Normal flow drains on chat-open so this is empty.
        self._drain_kind(HoldKind.ACTION, enabled, assignments)
        if self.global_chat_active:
            active_window = self.window_manager.get_active_window()
            window_ids = self.window_manager.get_window_ids()
            for i, is_enabled in enumerate(enabled):
                if not is_enabled or i >= len(window_ids):
                    continue
                win = window_ids[i]
                if win != active_window:
                    self._send_via_backend("key", win, "Escape")
        self._set_chat_active(False, cause="timeout")
        self.chat_active.clear()
        self._phantom_reset()

    def _resolve_keysym(self, key):
        """Fix #8: O(1) lookup. Delegates to the module-level _resolve_keysym
        so instance call sites and registry tests share one implementation."""
        return _resolve_keysym(key)

    def _key_phys_state(self, key):
        """Raw tri-state physical check (True held / False up / None unknown)
        via the Xlib backend's XQueryKeymap. None when no backend / unmappable
        / failure."""
        backend = self._xlib
        probe = getattr(backend, "key_physically_down", None)
        if probe is None:
            return None
        keysym = self._resolve_keysym(key) or key
        try:
            return probe(keysym)
        except Exception:
            return None

    def _key_still_physically_down(self, key) -> bool:
        """True ONLY when we can positively confirm (via XQueryKeymap on the
        Xlib backend) that `key` is still physically held. Returns False for
        every other case — no Xlib backend (Windows / xdotool), an unmappable
        key, or any query failure — so the caller falls back to the existing
        time-based release handling and behavior is unchanged off Linux/Xlib.
        Used to drop unpaired auto-repeat releases of a still-held co-key."""
        return self._key_phys_state(key) is True

    def _cc_window_ids(self) -> list:
        """Return the subset of managed windows that are CC windows.

        The wine bridge's helper only knows about CC windows in its
        prefix; passing the full window list (which may include TTR
        windows in mixed layouts) makes cross_check_sort_order's length
        comparison fail and forces a fallback to the xlib backend that
        Wine ignores. This helper provides the CC-only subset the bridge
        expects. Left-to-right sort order is preserved because the
        original list is already sorted that way by
        WindowManager.assign_windows.

        Known limitation: when multiple CC installs are running from
        different Wine prefixes (rare), the filter still returns all CC
        windows across prefixes. The per-prefix helper would then see a
        length mismatch. Out of scope for this fix; addressing it would
        require per-window prefix resolution at the routing layer.
        """
        try:
            from utils.game_registry import GameRegistry
            registry = GameRegistry.instance()
        except Exception:
            return []
        return [
            str(w) for w in self.window_manager.get_window_ids()
            if registry.get_game_for_window(str(w)) == "cc"
        ]

    def _send_via_backend(self, action: str, win_id: str, keysym: str, modifiers: list = None):
        """Route a synthetic key event through the active backend: the
        platform backend (Xlib / Win32 / MacOS), dropped-with-notice when that
        backend failed to initialize or is unavailable (win32/darwin have no
        fallback), or the Linux user's explicit xdotool backend."""
        if _ITRACE:
            try:
                _active = self.window_manager.get_active_window()
            except Exception:
                _active = "?"
            _itrace("send", f"action={action} target={win_id} active={_active} "
                            f"keysym={keysym} mods={modifiers}")
        import sys
        if sys.platform == "linux":
            try:
                from utils.game_registry import GameRegistry
                if GameRegistry.instance().get_game_for_window(str(win_id)) == "cc":
                    from utils import wine_input_bridge
                    if wine_input_bridge.send_to_window(
                        str(win_id),
                        self._cc_window_ids(),
                        action,
                        keysym,
                        modifiers,
                    ):
                        return
            except Exception as e:
                if self.logging_enabled:
                    self.input_log.emit(f"[Input] Wine bridge unavailable; falling back ({type(e).__name__})")

        success = True
        if self._xlib:
            if action == "keydown":
                success = self._xlib.send_keydown(win_id, keysym)
            elif action == "keyup":
                success = self._xlib.send_keyup(win_id, keysym)
            elif action == "key":
                success = self._xlib.send_key(win_id, keysym, modifiers)
        elif self._xlib_backend_failed or sys.platform != "linux":
            # The requested backend failed to initialize, OR this is darwin/win32
            # which have no xdotool fallback. NEVER silently emulate via
            # xdotool/XTEST here: XTEST re-triggers the Wayland input-control
            # portal the app deliberately avoids and can leave a stuck
            # auto-repeating key. Drop the event and surface once.
            if _ITRACE:
                _itrace("send", f"DROP (xlib unavailable) action={action} "
                                f"target={win_id} keysym={keysym}")
            if not self._xlib_unavailable_logged:
                self._xlib_unavailable_logged = True
                print("[InputService] input backend unavailable; dropping synthetic input")
                if self.logging_enabled:
                    self.input_log.emit(
                        "[Input] Input delivery unavailable; key input is being skipped."
                    )
            return
        else:
            # User explicitly selected the xdotool backend (intended; the
            # settings UI warns about the Wayland portal on GNOME).
            if action == "keydown":
                success = self._safe_run(["xdotool", "keydown", "--window", win_id, keysym])
            elif action == "keyup":
                success = self._safe_run(["xdotool", "keyup", "--window", win_id, keysym])
            elif action == "key":
                if modifiers:
                    combo = '+'.join(modifiers + [keysym])
                    success = self._safe_run(["xdotool", "key", "--window", win_id, combo])
                else:
                    success = self._safe_run(["xdotool", "key", "--window", win_id, keysym])

        if not success:
            self.window_manager.assign_windows()

    def _safe_run(self, cmd):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def release_all_keys(self):
        assignments = self._get_assignments(self.get_enabled_toons())
        enabled = self.get_enabled_toons()

        # Drain via _drain_all_held; for MOVEMENT keys this routes through
        # _send_logical_action_km which early-returns when global_chat_active
        # is True. Intentional: if chat is active, in-game keydowns were
        # never dispatched to bg toons, so the matching keyups must not be
        # either (see docs/superpowers/specs/2026-05-26-held-key-registry-design.md).
        self._drain_all_held(enabled, assignments)

        self.bg_typing_held.clear()
        self.chat_active.clear()
        # FSM orphan guard BEFORE the legacy resets (which are property-safe
        # no-ops afterwards): a mirrored bg box must not outlive the service
        # run that opened it.
        self._fsm_route_cleanup()
        self._set_chat_active(False, cause="release_all")
        self._phantom_reset()
        self._drain_focused_passthrough()

    def send_keep_alive_to_window(self, win_id, key, modifiers=None):
        """Send a single keep-alive keypress to a specific window."""
        keysym = self._resolve_keysym(key) or key
        if modifiers:
            self._send_via_backend("key", win_id, keysym, modifiers)
        else:
            self._send_via_backend("keydown", win_id, keysym)
            time.sleep(0.05)
            self._send_via_backend("keyup", win_id, keysym)


def _passthrough_keysyms_for_canonical(canonical: str) -> tuple[str, ...]:
    """Keys to recognize as passthrough while the grabber's active
    grab is in effect (so the focused window keeps responding to them).

    The set covers: the canonical movement keyset, modifiers, common
    action keys mapped by CC defaults, letters used by CC bindings
    (q, e for gags/tasks), digits, space/Tab/Return/Escape/Backspace.

    This is intentionally broad. The cost of recognizing an extra key
    is just a dict entry and a synthetic bridge send when it fires;
    the cost of MISSING a key is the focused toon losing that input
    while an arrow is held.
    """
    canonical_keys = tuple(
        _canonical_keys_for(canonical)
    )
    letters = tuple("abcdefghijklmnopqrstuvwxyz")
    digits = tuple("0123456789")
    return canonical_keys + PASSTHROUGH_KEYSYMS + letters + digits


def _canonical_keys_for(canonical: str) -> tuple[str, ...]:
    if canonical == "wasd":
        return ("w", "a", "s", "d")
    if canonical == "arrows":
        return ("Up", "Down", "Left", "Right")
    return ()
