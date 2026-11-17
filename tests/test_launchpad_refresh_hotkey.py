"""The app.refresh hotkey (F5 by default; Ctrl+Alt+R on macOS, where bare F5
is a media key) refreshes the session in the launchpad window.

The classic window's test pinned this through its own hook and the
Multitoon tab's manual refresh; this pins the same chain on LaunchpadWindow:
the default chord resolves to app.refresh through the window's hotkey
manager, and the action reaches ToonSession.refresh, except while a
Settings capture button is recording.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from tests.test_launchpad_window import isolated, window  # noqa: F401 (fixtures)
from utils.hotkey_actions import action_by_id

_REFRESH = action_by_id("app.refresh").default_chord
_MODS = frozenset(p for p in _REFRESH.split("+") if p in ("ctrl", "alt", "shift", "super"))
_KEYS = frozenset(p for p in _REFRESH.split("+") if p not in ("ctrl", "alt", "shift", "super"))


def _spy_refresh(window, monkeypatch):
    """Calls into ToonSession.refresh. The dispatch holds the bound method
    from when the window was wired, so the spy sits on the first thing
    refresh() asks, and answers "coalesced" so nothing else runs."""
    called = []
    monkeypatch.setattr(window.session, "_refresh_is_coalesced",
                        lambda now: called.append(1) or True)
    return called


@pytest.fixture
def no_global_grabs(monkeypatch):
    """Keep the window off the live X server's passive grabs."""
    monkeypatch.setattr("services.global_hotkeys.X11GlobalHotkeys.start",
                        lambda self: False)


def test_the_default_chord_refreshes_the_session(no_global_grabs, window, monkeypatch):
    if window.hotkeys is None:
        pytest.skip("no hotkey manager on this platform")
    hook = window.hotkeys.hotkey_manager._hotkey_hook
    assert hook(_MODS, _KEYS) == "app.refresh"
    called = _spy_refresh(window, monkeypatch)
    window._on_hotkey_action("app.refresh")
    assert called == [1]


def test_refresh_is_dropped_while_a_chord_is_being_recorded(no_global_grabs, window, monkeypatch):
    from utils import chord_capture_state
    called = _spy_refresh(window, monkeypatch)
    chord_capture_state.set_active(True)
    try:
        window._on_hotkey_action("app.refresh")
        assert called == []
    finally:
        chord_capture_state.set_active(False)
    window._on_hotkey_action("app.refresh")
    assert called == [1]
