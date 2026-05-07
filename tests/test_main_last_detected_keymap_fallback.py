"""When TTR's settings.json is unreadable on a given launch (e.g. TTR is
mid-update, the engine dir was renamed, etc.) but TTMT has previously
auto-detected and cached a keymap, the v2.2.0 release notes claim TTMT
falls back to the cached value. This test enforces that contract.

We don't import main.py directly — it constructs a QApplication and a full
window. Instead we extract the small refresh+apply helper into a pure
function that takes the dependencies as parameters, and test that.

If the fallback is implemented as a method on MultiToonTool, the test
constructs a stub instance with the minimum attributes the method needs.
"""
from unittest.mock import MagicMock


class _StubSettingsManager:
    def __init__(self, store):
        self._store = dict(store)
    def get(self, key, default=None):
        return self._store.get(key, default)
    def set(self, key, value):
        self._store[key] = value


def test_apply_cached_keymap_when_settings_json_unreadable(monkeypatch):
    """If _refresh_ttr_settings returns None but settings_manager has a
    last_detected_keymap, we must apply that cache to set 0 instead of
    silently leaving the keymap at WASD defaults."""
    from main import MultiToonTool

    # Build the smallest possible stub — we only need the helper, not the
    # full constructor.
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettingsManager({
        "last_detected_keymap": {
            "forward": "arrow_up", "reverse": "arrow_down",
            "left": "arrow_left", "right": "arrow_right",
            "jump": "control",
        },
    })
    keymap_calls = []
    instance.keymap_manager = MagicMock()
    instance.keymap_manager.update_set_key.side_effect = (
        lambda *a, **k: keymap_calls.append(a)
    )

    # Force the live-detect to "fail".
    monkeypatch.setattr(MultiToonTool, "_refresh_ttr_settings", lambda self: None)

    n = instance._apply_startup_ttr_keymap()
    assert n > 0, "Cached keymap must be applied when live detection fails"
    by_direction = {d: k for (_, d, k) in keymap_calls}
    assert by_direction["up"] == "Up"
    assert by_direction["jump"] == "Control_L"


def test_live_detection_takes_precedence_over_cache(monkeypatch):
    """If live settings.json is readable, it must overwrite the cache.
    Otherwise the user's most recent in-game rebind never takes effect
    until they restart with settings.json unreadable."""
    from main import MultiToonTool
    from utils.ttr_settings import TtrSettings

    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettingsManager({
        "last_detected_keymap": {"forward": "w", "jump": "space"},  # stale
    })
    keymap_calls = []
    instance.keymap_manager = MagicMock()
    instance.keymap_manager.update_set_key.side_effect = (
        lambda *a, **k: keymap_calls.append(a)
    )

    fresh = TtrSettings(
        controls={"forward": "arrow_up", "jump": "control"},
        chat_by_typing_enabled_resolved=True,
        has_letter_hotkeys=False,
        source_path=None,
    )
    monkeypatch.setattr(MultiToonTool, "_refresh_ttr_settings", lambda self: fresh)

    instance._apply_startup_ttr_keymap()
    by_direction = {d: k for (_, d, k) in keymap_calls}
    assert by_direction["up"] == "Up"
    assert by_direction["jump"] == "Control_L"
