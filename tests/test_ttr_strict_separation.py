"""Unit tests for TTR strict per-window keyset separation.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_ttr_strict_separation.py -v
"""
from types import SimpleNamespace

from services.input_service import STRICT_TTR_SEPARATION


def _make_service(monkeypatch, tmp_path, active_wid="100", windows=None,
                  games=None, assignments=None, settings=None):
    """Construct an InputService with stub deps; the run loop is never started."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.keymap_manager import KeymapManager
    from utils.game_registry import GameRegistry
    from services.input_service import InputService

    km = KeymapManager()
    windows = windows or []
    games = games or {}
    assignments = assignments or [0] * len(windows)

    monkeypatch.setattr(
        GameRegistry.instance(), "get_game_for_window",
        lambda wid: games.get(str(wid)),
    )

    wm = SimpleNamespace(
        get_active_window=lambda: active_wid,
        get_window_ids=lambda: windows,
        assign_windows=lambda: None,
    )

    store = dict(settings or {})
    sm = SimpleNamespace(
        get=lambda k, d=None: store.get(k, d),
        set=lambda k, v: store.__setitem__(k, v),
        on_change=lambda cb: None,
    )

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(windows),
        get_movement_modes=lambda: ["WASD"] * len(windows),
        get_event_queue_func=lambda: None,
        keymap_manager=km,
        get_keymap_assignments=lambda: assignments,
        settings_manager=sm,
    )
    return svc, km


def test_strict_ttr_enabled_defaults_true(monkeypatch, tmp_path):
    svc, _ = _make_service(monkeypatch, tmp_path)
    assert svc._strict_ttr_enabled() is True


def test_strict_ttr_enabled_reads_setting_false(monkeypatch, tmp_path):
    svc, _ = _make_service(monkeypatch, tmp_path,
                           settings={STRICT_TTR_SEPARATION: False})
    assert svc._strict_ttr_enabled() is False


def test_strict_ttr_active_false_without_installed_grabs(monkeypatch, tmp_path):
    """Toggle ON but grabs not installed for the focused window -> not active
    (router must fall back; _ttr_grabs_active defaults False)."""
    svc, _ = _make_service(monkeypatch, tmp_path)
    assert svc._ttr_grabs_active is False  # default
    assert svc._strict_ttr_active() is False


def test_strict_ttr_active_true_with_installed_grabs(monkeypatch, tmp_path):
    """Both conditions met (toggle ON + grabs installed for the focused TTR
    window): returns True."""
    svc, _ = _make_service(monkeypatch, tmp_path)
    svc._ttr_grabs_active = True
    assert svc._strict_ttr_active() is True


def test_strict_ttr_active_false_when_toggle_off(monkeypatch, tmp_path):
    svc, _ = _make_service(monkeypatch, tmp_path,
                           settings={STRICT_TTR_SEPARATION: False})
    svc._ttr_grabs_active = True
    assert svc._strict_ttr_active() is False


def test_canonical_set_for_ttr_arrows_default_toon(monkeypatch, tmp_path):
    svc, km = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    # TTR default set 0 forward == 'Up' -> arrows
    assert km.get_key_for_action("ttr", 0, "forward") == "Up"
    assert svc._canonical_set_for_toon_index(0) == "arrows"


def test_canonical_set_for_ttr_wasd_toon(monkeypatch, tmp_path):
    svc, km = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-2",
        windows=["ttr-1", "ttr-2"], games={"ttr-1": "ttr", "ttr-2": "ttr"},
        assignments=[0, 1],
    )
    # Build a WASD set at index 1 for ttr (set 0 stays the arrows default).
    km.add_set("ttr")  # creates set index 1
    km.update_set_key("ttr", 1, "forward", "w")
    km.update_set_key("ttr", 1, "reverse", "s")
    km.update_set_key("ttr", 1, "left", "a")
    km.update_set_key("ttr", 1, "right", "d")
    # toon index 1 -> assignment set 1 -> forward 'w' -> wasd
    assert svc._canonical_set_for_toon_index(1) == "wasd"


def test_canonical_set_for_ttr_custom_set_returns_none(monkeypatch, tmp_path):
    """A non-preset (custom) movement set yields None, which makes the grabber
    uninstall and the window fall back to today's behavior (no strict
    separation) - matching CC's preset-only capability."""
    svc, km = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-2",
        windows=["ttr-1", "ttr-2"], games={"ttr-1": "ttr", "ttr-2": "ttr"},
        assignments=[0, 1],
    )
    km.add_set("ttr")  # creates set index 1
    km.update_set_key("ttr", 1, "forward", "i")  # custom: neither 'w' nor 'Up'
    assert svc._canonical_set_for_toon_index(1) is None


def _capture_sends(svc):
    """Replace _send_via_backend with a recorder; return the list of calls.
    Also mark grabs as installed so _strict_ttr_active() is True (the run loop
    isn't started in unit tests, so _ttr_grabs_active would otherwise be False
    and the router would take the fallback path)."""
    sends = []
    svc._send_via_backend = lambda action, win, keysym, modifiers=None: sends.append(
        (action, str(win), keysym)
    )
    svc._ttr_grabs_active = True  # simulate grabs installed for the focused TTR window
    return sends


def _two_ttr_toons(monkeypatch, tmp_path, active_wid, settings=None):
    """Toon1 (ttr-1) on set 0 (the ARROWS default = TTR's shared native), and
    Toon2 (ttr-2) on set 1 (a WASD set we build). Returns (svc, km).
    Because the shared native is arrows, the outbound for 'forward' is 'Up'."""
    svc, km = _make_service(
        monkeypatch, tmp_path, active_wid=active_wid,
        windows=["ttr-1", "ttr-2"], games={"ttr-1": "ttr", "ttr-2": "ttr"},
        assignments=[0, 1], settings=settings or {STRICT_TTR_SEPARATION: True},
    )
    km.add_set("ttr")  # creates set index 1 (defaults to arrows)
    km.update_set_key("ttr", 1, "forward", "w")
    km.update_set_key("ttr", 1, "reverse", "s")
    km.update_set_key("ttr", 1, "left", "a")
    km.update_set_key("ttr", 1, "right", "d")
    return svc, km


def test_ttr_strict_focused_mismatched_key_synthesizes_to_focused(monkeypatch, tmp_path):
    """Toon2 focused, assigned WASD (set 1). User presses 'w'. The shared native
    (set 0) is arrows, so outbound for forward is 'Up'; 'w' != 'Up' -> synthesize
    'Up' to the focused window (strict ON). Toon1 (arrows set 0) ignores 'w'."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-2")
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert ("keydown", "ttr-2", "Up") in sends
    assert not any(w == "ttr-1" for (_, w, _) in sends)


def test_ttr_strict_focused_canonical_key_passes_native(monkeypatch, tmp_path):
    """Toon1 focused, assigned arrows (set 0 = native). User presses 'Up'.
    key == outbound 'Up', so the focused window is skipped (OS delivers it
    natively); no synth to ttr-1. Toon2 (wasd) doesn't bind 'Up' -> no synth."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-1")
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keydown", "Up", [True, True], [0, 1])
    assert not any(w == "ttr-1" for (_, w, _) in sends)


def test_ttr_strict_off_skips_focused_unconditionally(monkeypatch, tmp_path):
    """With the toggle OFF, the focused window is skipped even on a mismatched
    key (today's behavior). Toon2 focused (wasd), press 'w' -> no synth to it."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-2",
                             settings={STRICT_TTR_SEPARATION: False})
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert not any(w == "ttr-2" for (_, w, _) in sends)


def test_ttr_background_window_still_forwards(monkeypatch, tmp_path):
    """Regression: background TTR forwarding is unchanged. Toon1 focused
    (arrows), Toon2 background (wasd); pressing 'w' routes outbound 'Up' to
    background Toon2."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-1")
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert ("keydown", "ttr-2", "Up") in sends


def test_ttr_grabs_inactive_falls_back_to_skip(monkeypatch, tmp_path):
    """Toggle ON but grabs NOT installed for the focused window -> router keeps
    today's unconditional focused-window skip (no synth to the focused window),
    because without suppression the conditional-skip path would double-move the
    focused toon. This is the custom-set / non-game-focus state."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-2")
    sends = _capture_sends(svc)
    svc._ttr_grabs_active = False  # grabs not installed for this focus
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert not any(w == "ttr-2" for (_, w, _) in sends)


def test_ttr_strict_focused_mismatched_keyup_synthesizes_to_focused(monkeypatch, tmp_path):
    """keyup symmetry (load-bearing for VP hold-release): releasing 'w' on the
    focused WASD toon synthesizes keyup 'Up' to the focused window, mirroring the
    keydown. The skip conditional is action-agnostic, so down and up stay paired."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-2")
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keyup", "w", [True, True], [0, 1])
    assert ("keyup", "ttr-2", "Up") in sends
    assert not any(w == "ttr-1" for (_, w, _) in sends)


def test_ttr_strict_focused_native_keyup_passes_native(monkeypatch, tmp_path):
    """keyup of a native key on the focused arrows toon is skipped (the OS
    delivers the real keyup); no synth to ttr-1."""
    svc, km = _two_ttr_toons(monkeypatch, tmp_path, "ttr-1")
    sends = _capture_sends(svc)
    svc._send_logical_action_km("keyup", "Up", [True, True], [0, 1])
    assert not any(w == "ttr-1" for (_, w, _) in sends)
