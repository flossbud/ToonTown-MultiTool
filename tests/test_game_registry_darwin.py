"""Tests for the darwin-specific code paths in GameRegistry.

These tests pin sys.platform to "darwin" so they run on any host. They patch
ONLY module-level macos_discovery functions (monkeypatch-safe) and use
patch.object on the GameRegistry CLASS for staticmethods. They deliberately do
NOT monkeypatch the GameRegistry SINGLETON instance: pytest's monkeypatch
restore would leak the patched class staticmethod into the instance __dict__,
shadowing class-level patches in later tests (cross-test pollution).
"""

import importlib
from unittest.mock import patch

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
    # The darwin _get_pid_for_window resolves through macos_discovery.get_window_pid;
    # return None so PID-based identification yields nothing and the owner-name
    # fallback (game_for_window_id) is used. Patch module funcs only.
    monkeypatch.setattr(macos_discovery, "get_window_pid", lambda wid: None)
    monkeypatch.setattr(macos_discovery, "game_for_window_id",
                        lambda wid: "ttr" if wid == "11" else None)
    reg = gr.GameRegistry.instance()
    assert reg.get_game_for_window("11") == "ttr"


def test_classify_window_for_filtering_darwin_safe_deferral(monkeypatch):
    """Regression guard: classify on darwin must NOT confirm-reject a TTR window.

    On macOS _get_process_name returns None (no /proc). classify_window_for_filtering
    must therefore return (None, False) -- identity not confirmed, so the window is
    accepted by the heuristic fallback. Returning (None, True) would wrongly REJECT
    legitimate macOS TTR windows because the process name is not in _KNOWN_PROCESSES.
    """
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    # pid resolves (4242) but is not a launch-registered game -> get_game(4242) None.
    monkeypatch.setattr(macos_discovery, "get_window_pid", lambda wid: 4242)
    reg = gr.GameRegistry.instance()
    reg.unregister(4242)  # ensure get_game(4242) is None even if a prior test set it

    # Patch the class staticmethod via patch.object (restores the descriptor
    # cleanly, no singleton leak) so _get_process_name returns None on any host.
    with patch.object(gr.GameRegistry, "_get_process_name",
                      staticmethod(lambda pid: None)):
        game, confirmed = reg.classify_window_for_filtering("11")
    assert game is None
    assert confirmed is False, (
        "darwin classify must NOT confirm-reject (confirmed=True would wrongly "
        "filter out macOS TTR windows whose process name is not in _KNOWN_PROCESSES)"
    )
