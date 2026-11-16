"""Settings keys added for the next UI, and the named keep-alive keys."""

import json
import os

import pytest

from utils import settings_keys as sk


def _manager(tmp_path, contents=None):
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    if contents is not None:
        (cfg / "settings.json").write_text(json.dumps(contents))
    os.environ["TTMT_CONFIG_DIR"] = str(cfg)
    try:
        from utils.settings_manager import SettingsManager
        return SettingsManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)


def test_stored_strings():
    assert sk.FLOAT_STRIP_STYLE == "float_strip_style"
    assert sk.HIDE_WINDOW_WHEN_TOONS_UP == "hide_window_when_toons_up"
    assert sk.TRAY_ICON == "tray_icon"
    assert sk.KEYSET_EDITOR_LAYOUT == "keyset_editor_layout"
    assert sk.FLOAT_STRIP_STYLE_VALUES == ("neon", "flat")
    assert sk.KEYSET_EDITOR_LAYOUT_VALUES == ("list", "keys")


def test_keep_alive_keys_keep_their_stored_values():
    assert sk.KEEP_ALIVE_ENABLED == "keep_alive_enabled"
    assert sk.KEEP_ALIVE_CONSENT_ACKNOWLEDGED == "keep_alive_consent_acknowledged"


def test_defaults_registered(tmp_path):
    sm = _manager(tmp_path)
    assert sm.get(sk.FLOAT_STRIP_STYLE) == "neon"
    assert sm.get(sk.HIDE_WINDOW_WHEN_TOONS_UP) is True
    assert sm.get(sk.TRAY_ICON) is True
    assert sm.get(sk.KEYSET_EDITOR_LAYOUT) == "list"


def test_old_settings_file_keeps_values_and_gains_defaults(tmp_path):
    sm = _manager(tmp_path, {"theme": "dark", "keep_alive_enabled": True,
                             "keep_alive_consent_acknowledged": True})
    assert sm.get("theme") == "dark"
    assert sm.get(sk.KEEP_ALIVE_ENABLED) is True
    assert sm.get(sk.KEEP_ALIVE_CONSENT_ACKNOWLEDGED) is True
    assert sm.get(sk.FLOAT_STRIP_STYLE) == "neon"
    assert sm.get(sk.TRAY_ICON) is True


def test_stored_values_win_over_defaults(tmp_path):
    sm = _manager(tmp_path, {"float_strip_style": "flat", "tray_icon": False,
                             "hide_window_when_toons_up": False,
                             "keyset_editor_layout": "keys"})
    assert sm.get(sk.FLOAT_STRIP_STYLE) == "flat"
    assert sm.get(sk.TRAY_ICON) is False
    assert sm.get(sk.HIDE_WINDOW_WHEN_TOONS_UP) is False
    assert sm.get(sk.KEYSET_EDITOR_LAYOUT) == "keys"


@pytest.mark.parametrize("raw,want", [
    ("neon", "neon"), ("flat", "flat"), ("Flat", "neon"), (None, "neon"),
    (3, "neon"), (["flat"], "neon"),
])
def test_normalize_float_strip_style(raw, want):
    assert sk.normalize_float_strip_style(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("list", "list"), ("keys", "keys"), ("grid", "list"), (None, "list"),
    ({}, "list"),
])
def test_normalize_keyset_editor_layout(raw, want):
    assert sk.normalize_keyset_editor_layout(raw) == want
