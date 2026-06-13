"""Tests for the darwin-specific code paths in GameRegistry.

Pins sys.platform to "darwin" so they run on any host, patching only
module-level macos_discovery functions (monkeypatch-safe). They never
monkeypatch the GameRegistry SINGLETON instance for class staticmethods -- that
leaks the original into the instance __dict__ on restore and pollutes later
tests. The owner-fallback / classify tests use a bogus-but-resolving PID so the
REAL _get_process_name returns None through the absent-/proc path (no mocking of
_get_process_name), locking the actual darwin behavior the safety relies on.
"""

import importlib

gr = importlib.import_module("utils.game_registry")

# A PID that cannot correspond to a live process, so the real _get_process_name
# hits the /proc-miss (or no-/proc-on-macOS) path and returns None on darwin.
_BOGUS_PID = 2_000_000_000


def test_pid_for_window_darwin(monkeypatch):
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    monkeypatch.setattr(macos_discovery, "get_window_pid",
                        lambda wid: 4242 if wid == "11" else None)
    assert gr.GameRegistry._get_pid_for_window("11") == 4242
    assert gr.GameRegistry._get_pid_for_window("99") is None


def test_get_process_name_returns_none_on_darwin(monkeypatch):
    # Load-bearing real behavior: on darwin _get_process_name returns None (no
    # /proc), which is what makes classify defer instead of confirm-reject.
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    assert gr.GameRegistry._get_process_name(_BOGUS_PID) is None


def test_get_game_for_window_darwin_uses_owner(monkeypatch):
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    # PID RESOLVES (realistic), but it is not launch-registered and yields no
    # process-name / wine identity on darwin (the real _get_process_name returns
    # None), so the full chain falls through to the owner-name fallback.
    monkeypatch.setattr(macos_discovery, "get_window_pid", lambda wid: _BOGUS_PID)
    monkeypatch.setattr(macos_discovery, "game_for_window_id",
                        lambda wid: "ttr" if wid == "11" else None)
    reg = gr.GameRegistry.instance()
    reg.unregister(_BOGUS_PID)  # ensure get_game(_BOGUS_PID) is None
    assert reg.get_game_for_window("11") == "ttr"


def test_classify_window_for_filtering_darwin_safe_deferral(monkeypatch):
    """Regression guard: classify on darwin must NOT confirm-reject a TTR window.

    The PID resolves but is not a known game; on darwin the REAL _get_process_name
    returns None via the /proc-miss path (NOT mocked here), so classify must
    return (None, False) -- identity not confirmed, window accepted via owner-name
    identification. (None, True) would wrongly reject macOS TTR windows whose
    process name is not in _KNOWN_PROCESSES.
    """
    monkeypatch.setattr(gr.sys, "platform", "darwin", raising=False)
    from utils import macos_discovery
    monkeypatch.setattr(macos_discovery, "get_window_pid", lambda wid: _BOGUS_PID)
    reg = gr.GameRegistry.instance()
    reg.unregister(_BOGUS_PID)
    game, confirmed = reg.classify_window_for_filtering("11")
    assert game is None
    assert confirmed is False, (
        "darwin classify must NOT confirm-reject (confirmed=True would wrongly "
        "filter out macOS TTR windows whose process name is not in _KNOWN_PROCESSES)"
    )
