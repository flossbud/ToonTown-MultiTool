from utils.hotkey_actions import ACTIONS, action_by_id, effective_bindings
from utils.settings_keys import HOTKEY_BINDINGS


class _FakeSettings:
    def __init__(self, data=None):
        self._d = dict(data or {})
    def get(self, key, default=None):
        return self._d.get(key, default)


def test_registry_ids_and_defaults():
    ids = [a.id for a in ACTIONS]
    assert ids == [
        "overlay.toggle_cards", "overlay.scale_up", "overlay.scale_down",
        "launch.slot_1", "launch.slot_2", "launch.slot_3", "launch.slot_4",
        "service.toggle", "keepalive.toggle_all", "clicksync.toggle",
        "app.refresh",
        "profile.load_1", "profile.load_2", "profile.load_3",
        "profile.load_4", "profile.load_5",
    ]
    assert action_by_id("app.refresh").default_chord == "F5"
    assert action_by_id("profile.load_3").default_chord == "ctrl+3"
    assert action_by_id("overlay.toggle_cards").default_chord is None
    assert action_by_id("overlay.scale_up").repeat_ok is True
    assert action_by_id("service.toggle").repeat_ok is False


def test_effective_bindings_defaults_absent_null():
    # Empty config -> only the actions with defaults are bound.
    eff = effective_bindings(_FakeSettings())
    assert eff["app.refresh"] == "F5"
    assert eff["profile.load_1"] == "ctrl+1"
    assert "overlay.toggle_cards" not in eff
    # Explicit null CLEARS a default; explicit chord overrides it.
    eff = effective_bindings(_FakeSettings({
        HOTKEY_BINDINGS: {"app.refresh": None,
                          "overlay.toggle_cards": "ctrl+alt+h"}}))
    assert "app.refresh" not in eff
    assert eff["overlay.toggle_cards"] == "ctrl+alt+h"


def test_effective_bindings_drops_invalid_entries():
    eff = effective_bindings(_FakeSettings({
        HOTKEY_BINDINGS: {"app.refresh": "not a + chord +",
                          "no.such.action": "ctrl+9",
                          "clicksync.toggle": "h"}}))   # guardrail violation
    assert eff["app.refresh"] == "F5"     # invalid override -> default survives
    assert "no.such.action" not in eff
    assert "clicksync.toggle" not in eff


def test_default_chords_are_canonical_and_bindable():
    from utils.hotkey_chords import parse_chord, chord_error, format_chord
    for action in ACTIONS:
        if action.default_chord is None:
            continue
        chord = parse_chord(action.default_chord)
        assert chord_error(chord) is None, action.id
        assert format_chord(chord) == action.default_chord, action.id


def test_effective_bindings_canonicalizes_and_survives_wrong_type():
    eff = effective_bindings(_FakeSettings({
        HOTKEY_BINDINGS: {"overlay.toggle_cards": "alt+ctrl+H"}}))
    assert eff["overlay.toggle_cards"] == "ctrl+alt+h"
    eff = effective_bindings(_FakeSettings({HOTKEY_BINDINGS: "oops"}))
    assert eff["app.refresh"] == "F5"     # wrong-typed store -> defaults only
    assert "overlay.toggle_cards" not in eff


def test_make_hotkey_hook_matches_and_tracks_changes():
    from utils.hotkey_actions import make_hotkey_hook

    class _S(_FakeSettings):
        def __init__(self, data=None):
            super().__init__(data)
            self._cbs = []
        def on_change(self, cb):
            self._cbs.append(cb)
        def set(self, key, value):
            self._d[key] = value
            for cb in self._cbs:
                cb(key, value)

    s = _S()
    hook = make_hotkey_hook(s)
    assert hook(frozenset(), "F5") == "app.refresh"
    assert hook(frozenset({"ctrl"}), "2") == "profile.load_2"
    assert hook(frozenset({"ctrl", "alt"}), "h") is None
    s.set(HOTKEY_BINDINGS, {"overlay.toggle_cards": "ctrl+alt+h"})
    assert hook(frozenset({"ctrl", "alt"}), "h") == "overlay.toggle_cards"


def test_make_hotkey_hook_duplicate_chord_first_wins():
    from utils.hotkey_actions import make_hotkey_hook

    # overlay.toggle_cards precedes app.refresh (default F5) in ACTIONS order;
    # binding it to F5 creates a duplicate chord. First-wins, mirroring the
    # X11 provider's _compile_bindings.
    s = _FakeSettings({HOTKEY_BINDINGS: {"overlay.toggle_cards": "F5"}})
    hook = make_hotkey_hook(s)
    assert hook(frozenset(), "F5") == "overlay.toggle_cards"


def test_make_hotkey_hook_multikey_binding_never_matches_single_key():
    from utils.hotkey_actions import make_hotkey_hook

    # A multi-key chord is keyed by its full keys-set; the single-key lookup
    # can never match it (multi-key matching is the X provider's job until
    # the hook's callers grow held-set support).
    s = _FakeSettings({HOTKEY_BINDINGS: {"overlay.toggle_cards": "ctrl+h+t"}})
    hook = make_hotkey_hook(s)
    assert hook(frozenset({"ctrl"}), "h") is None
    assert hook(frozenset({"ctrl"}), "t") is None
    # single-key bindings still resolve
    assert hook(frozenset(), "F5") == "app.refresh"
