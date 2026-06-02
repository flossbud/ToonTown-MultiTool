from __future__ import annotations

import queue
import subprocess
import threading
import time
from functools import lru_cache
from PySide6.QtCore import QObject, Signal

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

    BACKSPACE_REPEAT_DELAY    = 0.4
    BACKSPACE_REPEAT_INTERVAL = 0.05
    AUTO_REPEAT_DEDUP_WINDOW  = 0.015

    def __init__(self, window_manager, get_enabled_toons, get_movement_modes, get_event_queue_func,
                 get_chat_enabled=None, settings_manager=None,
                 get_keymap_assignments=None, keymap_manager=None,
                 get_chat_block_list=None, get_chat_handling_mode=None):
        super().__init__()
        self.window_manager = window_manager
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_event_queue = get_event_queue_func
        self.get_chat_enabled = get_chat_enabled
        self.settings_manager = settings_manager
        self.get_keymap_assignments = get_keymap_assignments
        self.keymap_manager = keymap_manager
        # Resolved per call so changes to TTR's settings.json after service start
        # are honored without restarting the input thread. Default preserves the
        # legacy hard-coded behavior for callers that don't wire the helper.
        self.get_chat_block_list = get_chat_block_list or (lambda: {"Return", "Escape"})
        self.get_chat_handling_mode = get_chat_handling_mode
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self.logging_enabled = False

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
        # _xlib_backend_failed: True only when the xlib backend was REQUESTED
        # (input_backend == "xlib") but its connect() raised. Distinct from the
        # user explicitly selecting the xdotool backend. _send_via_backend reads
        # this to REFUSE a silent xdotool/XTEST fallback, which would re-trigger
        # the Wayland input-control portal the app deliberately avoids (and can
        # stick an auto-repeating key).
        self._xlib_backend_failed = False
        # One-shot guard so the "input delivery disabled" surfacing fires once
        # per failure episode, not on every dropped keystroke. Reset whenever a
        # working backend is (re)established. (Consumed in Task 2.)
        self._xlib_unavailable_logged = False
        self._key_grabber = None
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

    @property
    def keys_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.MOVEMENT))

    @property
    def modifiers_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.MODIFIER))

    @property
    def action_held(self) -> set[str]:
        return set(self.holds.keys_by_kind(HoldKind.ACTION))

    def start(self):
        if self.running and self.thread is not None and self.thread.is_alive():
            return
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=False)
        self.thread.start()
        self._start_key_grabber()

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
            ok = grabber.prepare(should_consume=self._should_consume_grabbed_key)
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
        # Record intent before any grabber call so the (possibly synchronous in
        # tests, async in production) completion callback observes the right
        # value. Default: not a TTR strict focus.
        self._intended_ttr_strict = False
        if self._key_grabber is None:
            return
        if not window_id:
            self._key_grabber.uninstall_grabs()
            return
        try:
            from utils.game_registry import GameRegistry
            game = GameRegistry.instance().get_game_for_window(str(window_id))
        except Exception:
            game = None
        # TTR strict separation is Linux/X11 only in v1 (Windows is a documented
        # follow-on); on Windows TTR keeps pre-feature behavior.
        if game == "ttr" and not (self._strict_ttr_enabled() and self._ttr_strict_supported()):
            self._key_grabber.uninstall_grabs()
            return
        if game not in ("cc", "ttr"):
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
            self._key_grabber.uninstall_grabs()
            return
        canonical = self._canonical_set_for_toon_index(toon_index)
        if canonical is None:
            self._key_grabber.uninstall_grabs()
            return
        # Set intent BEFORE install so on_grabs_changed credits this as a TTR
        # strict focus. CC focus installs the same way but intent stays False
        # (CC has its own always-on routing and must not flip the TTR gate).
        self._intended_ttr_strict = (game == "ttr")
        if game == "ttr":
            # X11-only (gated above); route both keysets, suppress native.
            if self.global_chat_active or self._phantom_active:
                # Input capture (chat/whisper) is active: keep grabs OFF so
                # keystrokes land natively in the focused TTR window. Intent
                # stays True so the capture-close resync reinstalls route_all.
                self._key_grabber.uninstall_grabs()
                return
            passthrough = list(_passthrough_keysyms_for_canonical(canonical))
            self._key_grabber.install_grabs(
                canonical_set=canonical, passthrough_keysyms=passthrough, route_all=True)
        else:
            # CC: legacy path. Omit route_all so the Win32 grabber (no such
            # kwarg) is never broken; the X11 grabber defaults route_all=False.
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

    def _should_consume_grabbed_key(self, keysym: str) -> bool:
        """Decide per-event whether to suppress the grabbed key from the
        focused window. Consume only when chat broadcast isn't active AND the
        active window is a CC window, or a TTR window with strict separation on.
        """
        if self.global_chat_active:
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
            return self._strict_ttr_enabled() and self._ttr_strict_supported()
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

    def _apply_backend_setting(self):
        """Connect or disconnect backend based on platform and current settings."""
        import sys
        if sys.platform == "win32":
            if self._xlib is None:
                try:
                    from utils.win32_backend import Win32Backend
                    self._xlib = Win32Backend()
                    self._xlib.connect()
                    self._xlib_backend_failed = False
                    self._xlib_unavailable_logged = False
                except Exception as e:
                    print(f"[InputService] Win32 backend unavailable: {e}")
                    self._xlib = None
                    self._xlib_backend_failed = True
                    # Leave _xlib_unavailable_logged as-is: it is reset only on
                    # recovery, so the drop message (Task 2) surfaces once per
                    # failure episode rather than every keystroke.
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
                    print(f"[InputService] Xlib backend unavailable; synthetic "
                          f"input disabled (refusing xdotool/XTEST fallback): {e}")
                    self._xlib = None
                    self._xlib_backend_failed = True
                    # Leave _xlib_unavailable_logged as-is: it is reset only on
                    # recovery, so the drop message (Task 2) surfaces once per
                    # failure episode rather than every keystroke.
                    if _ITRACE:
                        _itrace("backend", f"xlib connect FAILED: {e}")
                    if self.logging_enabled:
                        self.input_log.emit(
                            "[Input] Xlib backend unavailable; input delivery "
                            "disabled (refusing xdotool/XTEST fallback)"
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
        if self._xlib:
            self._xlib.disconnect()
            self._xlib = None



    # ── Keymap helpers ─────────────────────────────────────────────────────

    def _movement_keys(self) -> frozenset:
        """Return ALL movement keys across ALL sets so any set's keys enter the movement branch."""
        if self.keymap_manager:
            return self.keymap_manager.get_all_keys()
        return MOVEMENT_KEYS

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

        v1 is Linux/X11 only (`_ttr_strict_supported`); on Windows this is always
        False so TTR keeps pre-feature behavior. The `_key_grabber is not None`
        check is a safety net against a stale flag after teardown."""
        return (
            self._strict_ttr_enabled()
            and self._ttr_strict_supported()
            and self._key_grabber is not None
            and self._ttr_grabs_active
        )

    def _ttr_strict_supported(self) -> bool:
        """TTR strict separation is implemented for Linux/X11 in v1. Windows is a
        documented follow-on (the win32 grabber path is unvalidated for TTR), so
        the strict path stays off there and Windows keeps pre-feature behavior."""
        import sys
        return sys.platform != "win32"

    # ── Keymap-aware send methods ──────────────────────────────────────────

    def _send_logical_action_km(self, action, key, enabled, assignments):
        """Route a movement-class action to toons.

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
        """
        if self.global_chat_active:
            return
        if self.keymap_manager is None:
            return

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
            toon_game = registry.get_game_for_window(str(win))
            if toon_game is None:
                toon_game = "ttr"  # Windows fallback: TTMT pre-dates CC support and TTR is the safe default
            set_idx = assignments[i] if i < len(assignments) else 0

            if toon_game == "cc":
                toon_action = self.keymap_manager.get_action_in_set("cc", set_idx, key)
                if toon_action is None and set_idx != 0:
                    # The toon is on a non-default set that does not bind
                    # this key. Sets in TTMT are movement-only overrides:
                    # non-movement bindings (jump, sprint, map, etc.) live
                    # only in the default set. Fall back to the default
                    # set's binding -- but ONLY when the resolved action
                    # is non-movement. Movement actions stay strict per-
                    # toon so a key the toon's set explicitly does not
                    # bind for movement is not forwarded as movement.
                    default_action = self.keymap_manager.get_action_in_set("cc", 0, key)
                    if default_action is not None and default_action not in _MOVEMENT_ACTIONS:
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
                    if self.logging_enabled and action == "keydown" and key != canonical:
                        self.input_log.emit(
                            f"[Input] '{key}' -> '{canonical}' "
                            f"(cc action: {toon_action}, set {set_idx + 1})"
                        )
            else:
                # Strict per-toon for movement; default-set fallback for
                # non-movement actions only. Sets in TTMT are movement-
                # only overrides; non-movement bindings (jump, etc.) live
                # only in the default set. Outbound stays sourced from
                # set 0 (native binding).
                toon_action = self.keymap_manager.get_action_in_set(toon_game, set_idx, key)
                if toon_action is None and set_idx != 0:
                    default_action = self.keymap_manager.get_action_in_set(toon_game, 0, key)
                    if default_action is not None and default_action not in _MOVEMENT_ACTIONS:
                        toon_action = default_action
                if toon_action is None:
                    continue
                if not logical_actions.supports(toon_game, toon_action):
                    continue
                outbound = self.keymap_manager.get_key_for_action(toon_game, 0, toon_action)
                if outbound is None:
                    continue
                if win == active_window and not self._strict_ttr_active() \
                        and not self._strict_drain_active:
                    # Strict not enforceable (toggle OFF or grabs not installed):
                    # the focused window still receives its native key -> skip.
                    # When strict IS active, route_all suppressed the native key
                    # for matched AND mismatched keys, so synthesize to the
                    # focused toon too (no key == outbound skip).
                    # _strict_drain_active bypasses this skip during an explicit
                    # synchronous drain on toggle-off / capture-open, so the
                    # focused toon's synthesized keydown is paired with a keyup.
                    continue
                keysym = self._resolve_keysym(outbound)
                if keysym:
                    self._send_via_backend(action, win, keysym)
                    if self.logging_enabled and action == "keydown" and key != outbound:
                        self.input_log.emit(
                            f"[Input] '{key}' -> '{outbound}' "
                            f"(action: {toon_action}, {toon_game} set {set_idx + 1})"
                        )

    def _dispatch_keyup_for_entry(self, entry, enabled, assignments) -> None:
        """Single-site keyup routing by HoldKind. Used by _dispatch_keyup
        on individual releases and by the drain helpers on bulk drains.
        Extracted so any future change to a kind's dispatch path lands
        in one place."""
        if entry.kind == HoldKind.MODIFIER:
            self._send_modifier_to_bg("keyup", entry.key, enabled, assignments)
        elif entry.kind == HoldKind.MOVEMENT:
            self._send_logical_action_km("keyup", entry.key, enabled, assignments)
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
            self._send_via_backend("key", win, "BackSpace")

    # ── Run loop ───────────────────────────────────────────────────────────

    def run(self):
        self._apply_backend_setting()
        event_queue    = self.get_event_queue()
        bs_press_time  = None
        bs_last_repeat = 0.0
        pending_keyups: dict[str, float] = {}

        try:
            while self.running:
                if not self.should_send_input():
                    while not event_queue.empty():
                        try:
                            event_queue.get_nowait()
                        except queue.Empty:
                            break
                    if len(self.holds) > 0:
                        enabled     = self.get_enabled_toons()
                        assignments = self._get_assignments(enabled)
                        self._drain_all_held(enabled, assignments)
                    self.bg_typing_held.clear()
                    pending_keyups.clear()
                    self._phantom_reset()
                    if self.global_chat_active:
                        self._set_chat_active(False)
                        self.chat_active.clear()
                    bs_press_time  = None
                    bs_last_repeat = 0.0
                    self._stop_event.wait(0.01)
                    continue

                now            = time.monotonic()
                enabled        = self.get_enabled_toons()
                assignments    = self._get_assignments(enabled)
                movement_keys  = self._movement_keys()

                # Idle timeout — reset chat state if no typing for 15s
                if (self.global_chat_active or self._phantom_active) and self._chat_last_activity > 0:
                    if now - self._chat_last_activity > self.CHAT_IDLE_TIMEOUT:
                        self._timeout_reset_chat(enabled, assignments)

                # Phantom gate — clear stale phantom state if the gate has closed
                # since activation (e.g. user toggled chat off on the last
                # chat-enabled bg toon while phantom was already suppressing).
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
                        continue
                    if action == "keyup":
                        pending_keyups[key] = now
                        continue

                    if action == "keydown":

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

                        if is_modifier:
                            if self.holds.acquire(key, HoldKind.MODIFIER, now):
                                self._send_modifier_to_bg("keydown", key, enabled, assignments)

                        elif is_movement:
                            if self.holds.acquire(key, HoldKind.MOVEMENT, now):
                                if self.logging_enabled:
                                    logical = self._resolve_logical_action(key)
                                    extra = f" (action: {logical})" if logical else ""
                                    self._log_key(key, "pressed", extra)
                                if self._phantom_active:
                                    # Stealth chat — suppress movement to bg toons
                                    self._chat_last_activity = now
                                else:
                                    self._send_logical_action_km("keydown", key, enabled, assignments)
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

                        elif key == "Return":
                            if key not in self.bg_typing_held:
                                self.bg_typing_held.add(key)
                                self._log_key(key, "pressed")
                                if self._phantom_active:
                                    # Whisper send detected — don't toggle chat on bg toons
                                    self._phantom_reset()
                                else:
                                    self._set_chat_active(not self.global_chat_active)
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
                                was_chatting = self.global_chat_active
                                self._set_chat_active(False)
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
                        if self._dispatch_keyup(stale_key, enabled, assignments):
                            bs_press_time  = None
                            bs_last_repeat = 0.0

                if bs_press_time is not None and self.holds.contains("BackSpace") and not self._phantom_active:
                    held_for = now - bs_press_time
                    if held_for >= self.BACKSPACE_REPEAT_DELAY:
                        if now - bs_last_repeat >= self.BACKSPACE_REPEAT_INTERVAL:
                            bs_last_repeat = now
                            self._send_backspace_to_background(enabled, assignments)

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
            return
        try:
            if capturing:
                self._key_grabber.uninstall_grabs()
            else:
                seed = self.window_manager.get_active_window()
                self._on_active_window_changed_for_grabber(seed or "")
        except Exception as e:  # noqa: BLE001
            print(f"[InputService] capture grab resync failed: {e}")

    def _set_chat_active(self, active: bool):
        """Set global_chat_active and emit signal on change."""
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
        # Hard gate: when global Chat Handling mode is anything other than
        # 'advanced' (Simple mode being the default), phantom is off
        # regardless of per-toon chat state. Legacy callers that pass
        # get_chat_handling_mode=None get advanced-equivalent behavior.
        if self.get_chat_handling_mode is not None:
            if self.get_chat_handling_mode() != "advanced":
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
        self._set_chat_active(False)
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
        """Route input through Xlib or xdotool depending on USE_XLIB_BACKEND."""
        if _ITRACE:
            try:
                _active = self.window_manager.get_active_window()
            except Exception:
                _active = "?"
            _itrace("send", f"action={action} target={win_id} active={_active} "
                            f"keysym={keysym} mods={modifiers}")
        import sys
        if sys.platform != "win32":
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
        else:
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
        self._set_chat_active(False)
        self._phantom_reset()

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
