"""Pure hotkey action registry - the single source of bindable actions.

Dispatch deliberately lives elsewhere (utils/hotkey_dispatch.py wires ids
to live objects); this module must stay importable with no Qt/X deps.

Binding resolution: settings[HOTKEY_BINDINGS] maps action_id -> chord
string or None. ABSENT id = use the registry default (so F5/Ctrl+1..5
work on first run with no migration); EXPLICIT None = user cleared the
binding. Invalid ids/chords are dropped defensively (hand-edited config).
"""
from __future__ import annotations

from dataclasses import dataclass

from utils.hotkey_chords import parse_chord, chord_error, format_chord
from utils.settings_keys import HOTKEY_BINDINGS


@dataclass(frozen=True)
class HotkeyAction:
    id: str
    label: str
    category: str          # Settings-card grouping
    default_chord: str | None = None
    repeat_ok: bool = False   # accept X auto-repeat while held


ACTIONS = (
    HotkeyAction("overlay.toggle_cards", "Hide/Show cards", "Float UI"),
    HotkeyAction("overlay.scale_up", "Scale cluster up", "Float UI",
                 repeat_ok=True),
    HotkeyAction("overlay.scale_down", "Scale cluster down", "Float UI",
                 repeat_ok=True),
    HotkeyAction("launch.slot_1", "Launch account slot 1", "Launch"),
    HotkeyAction("launch.slot_2", "Launch account slot 2", "Launch"),
    HotkeyAction("launch.slot_3", "Launch account slot 3", "Launch"),
    HotkeyAction("launch.slot_4", "Launch account slot 4", "Launch"),
    HotkeyAction("service.toggle", "Start/Stop service", "Multitoon"),
    HotkeyAction("keepalive.toggle_all", "Toggle keep-alive (all)",
                 "Multitoon"),
    HotkeyAction("clicksync.toggle", "Toggle Click Sync", "Multitoon"),
    HotkeyAction("app.refresh", "Refresh", "Multitoon",
                 default_chord="F5"),
    HotkeyAction("profile.load_1", "Load profile 1", "Profiles",
                 default_chord="ctrl+1"),
    HotkeyAction("profile.load_2", "Load profile 2", "Profiles",
                 default_chord="ctrl+2"),
    HotkeyAction("profile.load_3", "Load profile 3", "Profiles",
                 default_chord="ctrl+3"),
    HotkeyAction("profile.load_4", "Load profile 4", "Profiles",
                 default_chord="ctrl+4"),
    HotkeyAction("profile.load_5", "Load profile 5", "Profiles",
                 default_chord="ctrl+5"),
)

_BY_ID = {a.id: a for a in ACTIONS}


def action_by_id(action_id: str) -> HotkeyAction:
    return _BY_ID[action_id]


def effective_bindings(settings_manager) -> dict[str, str]:
    """action_id -> canonical chord string, for every BOUND action."""
    stored = settings_manager.get(HOTKEY_BINDINGS, {}) or {}
    if not isinstance(stored, dict):
        stored = {}                       # hand-edited config: wrong type
    out: dict[str, str] = {}
    for action in ACTIONS:
        if action.id in stored:
            chord_text = stored[action.id]
            if chord_text is None:
                continue                      # explicitly cleared
            try:
                chord = parse_chord(chord_text)
            except ValueError:
                chord_text = action.default_chord      # corrupt -> default
            else:
                if chord_error(chord) is not None:
                    continue                  # guardrail violation -> unbound
                chord_text = format_chord(chord)
        else:
            chord_text = action.default_chord
        if chord_text:
            out[action.id] = chord_text
    return out


def make_hotkey_hook(settings_manager):
    """(mods: frozenset, key: str) -> action_id|None against the CURRENT
    effective bindings. Rebuilds its table on HOTKEY_BINDINGS changes via
    the manager's on_change (cheap: the table is a small dict).

    The table is keyed by the chord's full keys-frozenset; the lookup wraps
    its single incoming key, so a MULTI-KEY binding can never match here.
    Multi-key chords are matched only by the X provider, until this hook's
    callers grow held-set support (the sync-grab arming task)."""
    table = {}

    def _rebuild(*_a):
        table.clear()
        for action_id, chord_text in effective_bindings(settings_manager).items():
            c = parse_chord(chord_text)
            # First-wins on duplicate chords (effective_bindings iterates in
            # ACTIONS order), mirroring the X11 provider's _compile_bindings.
            table.setdefault((c.mods, c.keys), action_id)

    _rebuild()
    on_change = getattr(settings_manager, "on_change", None)
    if on_change is not None:
        on_change(lambda key, _v: _rebuild() if key == HOTKEY_BINDINGS else None)
    return lambda mods, key: table.get((frozenset(mods), frozenset({key})))
