"""Tests for the darwin-specific code paths in GameRegistry.

These tests monkeypatch sys.platform to "darwin" so they run on any host.
"""

import importlib

gr = importlib.import_module("utils.game_registry")


def test_pid_for_window_darwin(monkeypatch):
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    monkeypatch.setattr(macos_discovery, "get_window_pid",
                        lambda wid: 4242 if wid == "11" else None)
    assert gr.GameRegistry._get_pid_for_window("11") == 4242
    assert gr.GameRegistry._get_pid_for_window("99") is None


def test_get_game_for_window_darwin_uses_owner(monkeypatch):
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    monkeypatch.setattr(macos_discovery, "game_for_window_id",
                        lambda wid: "ttr" if wid == "11" else None)
    reg = gr.GameRegistry.instance()
    # PID path yields nothing on darwin (no launch-registry / proc); falls back
    # to the owner-name lookup.
    monkeypatch.setattr(reg, "_get_pid_for_window", lambda wid: None)
    assert reg.get_game_for_window("11") == "ttr"


def test_classify_window_for_filtering_darwin_safe_deferral(monkeypatch):
    """Regression guard: classify on darwin must NOT confirm-reject a TTR window.

    On macOS _get_process_name raises FileNotFoundError (no /proc) and returns
    None.  classify_window_for_filtering must therefore return (None, False) --
    identity not confirmed, so the window is accepted by the heuristic fallback.
    Returning (None, True) would wrongly REJECT legitimate macOS TTR windows
    because the process name is not in _KNOWN_PROCESSES.
    """
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)

    reg = gr.GameRegistry.instance()

    # Ensure the pid (4242) is not registered so get_game(4242) returns None.
    reg.unregister(4242)

    monkeypatch.setattr(reg, "_get_pid_for_window", lambda wid: 4242)
    # _get_process_name returns None on macOS (/proc miss).
    monkeypatch.setattr(reg, "_get_process_name", lambda pid: None)

    game, confirmed = reg.classify_window_for_filtering("11")
    assert game is None
    assert confirmed is False, (
        "darwin classify must NOT confirm-reject (confirmed=True would wrongly "
        "filter out macOS TTR windows whose process name is not in _KNOWN_PROCESSES)"
    )
