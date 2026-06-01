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


def test_strict_ttr_active_false_without_grabber(monkeypatch, tmp_path):
    """Toggle ON but no grabber armed -> not active (router must fall back)."""
    svc, _ = _make_service(monkeypatch, tmp_path)
    svc._key_grabber = None
    assert svc._strict_ttr_active() is False


def test_strict_ttr_active_true_with_grabber(monkeypatch, tmp_path):
    """Both conditions met (toggle ON + a grabber exists): returns True."""
    svc, _ = _make_service(monkeypatch, tmp_path)
    svc._key_grabber = object()  # sentinel: a grabber exists
    assert svc._strict_ttr_active() is True


def test_strict_ttr_active_false_when_toggle_off(monkeypatch, tmp_path):
    svc, _ = _make_service(monkeypatch, tmp_path,
                           settings={STRICT_TTR_SEPARATION: False})
    svc._key_grabber = object()
    assert svc._strict_ttr_active() is False
