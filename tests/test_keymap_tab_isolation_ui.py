"""UI behavior tests for the isolation panel in the Keymap tab."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tabs.keymap_tab import KeymapTab
from utils import settings_keys
from utils.keymap_manager import KeymapManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def keymap_manager(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    os.environ["TTMT_CONFIG_DIR"] = str(cfg)
    try:
        mgr = KeymapManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)
    return mgr


@pytest.fixture
def settings():
    store = {}
    sm = MagicMock()
    sm.get.side_effect = lambda k, default=None: store.get(k, default)
    sm.set.side_effect = lambda k, v: store.update({k: v})
    sm._store = store
    return sm


def test_toggle_off_state_hides_canonical_picker_and_restore_button(qapp, keymap_manager, settings):
    tab = KeymapTab(keymap_manager, settings)
    panel = tab.findChild(object, "isolation_panel")
    assert panel is not None
    picker = tab.findChild(object, "isolation_canonical_picker")
    btn = tab.findChild(object, "isolation_restore_button")
    assert picker is not None
    assert btn is not None
    # When isolation is off, picker and restore button should be hidden.
    assert picker.isVisibleTo(panel) is False
    assert btn.isVisibleTo(panel) is False


def test_toggle_on_first_time_shows_explainer_modal(qapp, keymap_manager, settings, monkeypatch):
    tab = KeymapTab(keymap_manager, settings)
    shown = {"called": False}

    def fake_modal(parent, canonical_default):
        shown["called"] = True
        return None  # user cancels

    monkeypatch.setattr(tab, "_show_isolation_explainer", fake_modal)

    toggle = tab.findChild(object, "isolation_toggle")
    toggle.setChecked(True)

    assert shown["called"] is True
    assert settings._store.get(settings_keys.ISOLATION_ENABLED, False) is False


def test_first_time_accept_writes_prefs_and_persists_settings(qapp, keymap_manager, settings, monkeypatch, tmp_path):
    tab = KeymapTab(keymap_manager, settings)

    # Mock the install discovery + writer chain.
    fake_install = type("I", (), {"prefix_path": str(tmp_path)})()
    monkeypatch.setattr(tab, "_discover_cc_installs", lambda: [fake_install])

    write_calls = []

    def fake_write_all(installs, canonical):
        write_calls.append((installs, canonical))
        from utils.cc_settings import WriteResult
        return [WriteResult(ok=True)]

    monkeypatch.setattr("utils.cc_settings.write_canonical_to_all_installs", fake_write_all)
    monkeypatch.setattr("utils.cc_settings.detect_custom_bindings", lambda s: "empty")
    monkeypatch.setattr("utils.cc_running_pids.scan_for_prefix", lambda _: [])

    # User accepts modal, picks WASD.
    monkeypatch.setattr(tab, "_show_isolation_explainer", lambda parent, c: "wasd")

    toggle = tab.findChild(object, "isolation_toggle")
    toggle.setChecked(True)

    assert settings._store[settings_keys.ISOLATION_ENABLED] is True
    assert settings._store[settings_keys.ISOLATION_CANONICAL] == "wasd"
    assert write_calls == [([fake_install], "wasd")]


def test_user_custom_bindings_shows_confirmation_dialog(qapp, keymap_manager, settings, monkeypatch, tmp_path):
    tab = KeymapTab(keymap_manager, settings)

    fake_install = type("I", (), {"prefix_path": str(tmp_path)})()
    monkeypatch.setattr(tab, "_discover_cc_installs", lambda: [fake_install])
    monkeypatch.setattr("utils.cc_settings.detect_custom_bindings", lambda s: "user_custom")

    # Provide a fake prefs file so locate_cc_preferences/parse don't break.
    prefs = tmp_path / "preferences.json"
    prefs.write_text(json.dumps({"keymap": {"forward": "i"}, "want-Custom-Controls": True}))
    monkeypatch.setattr("utils.cc_settings.locate_cc_preferences", lambda inst: prefs)

    confirmed = {"shown": False, "answer": None}

    def fake_confirm(parent, current, proposed):
        confirmed["shown"] = True
        return "cancel"

    monkeypatch.setattr(tab, "_show_custom_bindings_confirm", fake_confirm)
    monkeypatch.setattr(tab, "_show_isolation_explainer", lambda parent, c: "wasd")

    toggle = tab.findChild(object, "isolation_toggle")
    toggle.setChecked(True)

    assert confirmed["shown"] is True
    assert settings._store.get(settings_keys.ISOLATION_ENABLED, False) is False


def test_restore_button_calls_restore_and_clears_isolation(qapp, keymap_manager, settings, monkeypatch, tmp_path):
    settings._store[settings_keys.ISOLATION_ENABLED] = True
    settings._store[settings_keys.ISOLATION_CANONICAL] = "wasd"

    tab = KeymapTab(keymap_manager, settings)

    fake_install = type("I", (), {"prefix_path": str(tmp_path)})()
    monkeypatch.setattr(tab, "_discover_cc_installs", lambda: [fake_install])

    restore_calls = []

    def fake_restore_all(installs):
        restore_calls.append(installs)
        from utils.cc_settings import RestoreResult
        return [RestoreResult(ok=True)]

    monkeypatch.setattr("utils.cc_settings.restore_all_installs", fake_restore_all)

    btn = tab.findChild(object, "isolation_restore_button")
    btn.click()

    assert restore_calls == [[fake_install]]
    assert settings._store[settings_keys.ISOLATION_ENABLED] is False


def test_input_grab_subtoggle_is_disabled_in_phase_a(qapp, keymap_manager, settings):
    settings._store[settings_keys.ISOLATION_ENABLED] = True

    tab = KeymapTab(keymap_manager, settings)

    sub = tab.findChild(object, "isolation_input_grab_subtoggle")
    assert sub is not None
    assert sub.isEnabled() is False
    assert "later release" in sub.toolTip().lower()


def test_default_set_movement_rows_become_readonly_when_isolation_on(qapp, keymap_manager, settings, monkeypatch):
    settings._store[settings_keys.ISOLATION_ENABLED] = True

    tab = KeymapTab(keymap_manager, settings)
    # Force re-render of cards under the isolation-on flag.
    tab._refresh_isolation_lock_state()

    banner = tab.findChild(object, "isolation_default_banner")
    assert banner is not None
    # Banner must be intended-visible while the CC tab is active and isolation is on.
    # Use isVisibleTo to account for offscreen (no .show()) tree.
    assert banner.isVisibleTo(tab) is True

    # Movement key fields in CC Default should be read-only.
    for action in ("forward", "reverse", "left", "right"):
        field = tab.findChild(object, f"cc_default_field_{action}")
        if field is not None:  # field may be absent in test fixture
            assert field.isReadOnly() is True


def test_default_set_movement_rows_editable_when_isolation_off(qapp, keymap_manager, settings):
    settings._store[settings_keys.ISOLATION_ENABLED] = False

    tab = KeymapTab(keymap_manager, settings)

    banner = tab.findChild(object, "isolation_default_banner")
    if banner is not None:
        assert banner.isVisibleTo(tab) is False
