"""Cross-set conflict detection + Default-set config lock.

Cross-set: one key bound to DIFFERENT actions in two sets of the same game
is a conflict (a single press drives two toons differently); the same action
on the same key across sets is broadcast-normal (added sets seed from the
game defaults) and must stay clean.

Lock: while a game config file is found (TTR settings.json live or cached,
CC preferences.json on any discovered install), the Default set's key fields
are read-only - the config is the source of truth and startup re-applies it,
so hand edits would be misleading or silently clobbered.
"""
from __future__ import annotations

import json
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from utils.keymap_manager import KeymapManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_manager(tmp_path, contents=None):
    """KeymapManager pinned to an isolated temp config dir (never the real
    one: TTMT_CONFIG_DIR is set for the constructor only, and the manager
    caches its file path at init)."""
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    if contents is not None:
        (cfg / "keymaps.json").write_text(json.dumps(contents))
    os.environ["TTMT_CONFIG_DIR"] = str(cfg)
    try:
        mgr = KeymapManager()
    finally:
        os.environ.pop("TTMT_CONFIG_DIR", None)
    return mgr


def _patch_no_configs(monkeypatch):
    """Make both games' config sources deterministically absent."""
    import utils.ttr_settings as ttr_settings
    import services.ttr_login_service as ttr_login
    import services.wine_runtimes as wine_runtimes
    monkeypatch.setattr(ttr_settings, "locate_settings_file",
                        lambda engine_dir=None: None)
    monkeypatch.setattr(ttr_login, "find_engine_path", lambda: None)
    monkeypatch.setattr(wine_runtimes, "discover_cc_installs", lambda: [])


class _FakeSettings:
    def __init__(self, **vals):
        self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        self._d.update(vals)
        self._callbacks: list = []

    def get(self, k, default=None):
        return self._d.get(k, default)

    def set(self, k, v):
        old = self._d.get(k)
        self._d[k] = v
        if old != v:
            for cb in self._callbacks:
                cb(k, v)

    def on_change(self, cb):
        self._callbacks.append(cb)


def _make_tab(mgr, settings=None):
    from tabs.keymap_tab import KeymapTab
    return KeymapTab(mgr, settings_manager=settings or _FakeSettings())


def _field(tab, game, set_index, action):
    from tabs.keymap_tab import MovementKeyField
    card = tab._entries_by_game[game][set_index]["card"]
    return card.findChild(MovementKeyField, f"key_field_{action}")


# ── Manager: cross_set_conflicts ───────────────────────────────────────────


def test_cross_set_different_actions_is_conflict(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "Alt_L")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "Alt_L")
    conflicts = mgr.cross_set_conflicts("ttr")
    assert (0, "book", 1, "jump", "Alt_L") in conflicts


def test_cross_set_same_action_same_key_is_clean(tmp_path):
    # add_set seeds every action from the game defaults, so a fresh
    # alternate set duplicates Default's keys action-for-action. That is
    # the broadcast case and must never be reported.
    mgr = _make_manager(tmp_path)
    mgr.add_set("ttr")
    assert mgr.cross_set_conflicts("ttr") == []


def test_intra_set_duplicate_not_reported_by_cross_api(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "gags", "p")
    mgr.update_set_key("ttr", 0, "tasks", "p")
    assert mgr.cross_set_conflicts("ttr") == []


def test_cross_set_conflicts_scoped_per_game(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "Alt_L")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "Alt_L")
    assert mgr.cross_set_conflicts("ttr") != []
    assert mgr.cross_set_conflicts("cc") == []


def test_cross_set_conflicts_three_sets_all_pairs(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "F9")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "F9")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 2, "gags", "F9")
    conflicts = mgr.cross_set_conflicts("ttr")
    assert (0, "book", 1, "jump", "F9") in conflicts
    assert (0, "book", 2, "gags", "F9") in conflicts
    assert (1, "jump", 2, "gags", "F9") in conflicts


# ── Tab: conflict painting across cards ────────────────────────────────────


def test_cross_set_conflict_paints_both_cards(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "Alt_L")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "Alt_L")
    tab = _make_tab(mgr)
    book = _field(tab, "ttr", 0, "book")
    jump = _field(tab, "ttr", 1, "jump")
    assert book.property("conflict") == "true"
    assert jump.property("conflict") == "true"
    assert "in" in book.toolTip() and "Jump" in book.toolTip()
    assert "Book" in jump.toolTip() and "Default" in jump.toolTip()


def test_fresh_alternate_set_paints_nothing(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    mgr.add_set("ttr")
    tab = _make_tab(mgr)
    from utils import logical_actions
    for set_index in (0, 1):
        for action in logical_actions.actions_for("ttr"):
            f = _field(tab, "ttr", set_index, action)
            assert f.property("conflict") != "true", (set_index, action)


def test_intra_alternate_set_conflict_paints(qapp, tmp_path, monkeypatch):
    # Pre-change behavior only ever painted the Default card; an internal
    # duplicate inside an alternate set must now paint red too.
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "gags", "p")
    mgr.update_set_key("ttr", 1, "tasks", "p")
    tab = _make_tab(mgr)
    gags = _field(tab, "ttr", 1, "gags")
    tasks = _field(tab, "ttr", 1, "tasks")
    assert gags.property("conflict") == "true"
    assert tasks.property("conflict") == "true"
    assert "Tasks" in gags.toolTip()


def test_conflict_clears_after_rebind(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "Alt_L")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "Alt_L")
    tab = _make_tab(mgr)
    assert _field(tab, "ttr", 1, "jump").property("conflict") == "true"
    tab._on_key_changed_for_game("ttr", 1, "jump", "Alt_R")
    assert _field(tab, "ttr", 1, "jump").property("conflict") == "false"
    assert _field(tab, "ttr", 0, "book").property("conflict") == "false"


# ── Tab: Default-set lock ──────────────────────────────────────────────────


def test_default_unlocked_when_no_config_found(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    tab = _make_tab(mgr)
    field = _field(tab, "ttr", 0, "book")
    assert not field.is_locked()
    QTest.mouseClick(field, Qt.LeftButton)
    assert field._awaiting is True


def test_default_locked_when_ttr_settings_found(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    import utils.ttr_settings as ttr_settings
    monkeypatch.setattr(ttr_settings, "locate_settings_file",
                        lambda engine_dir=None: "/fake/settings.json")
    mgr = _make_manager(tmp_path)
    mgr.add_set("ttr")
    tab = _make_tab(mgr)
    from utils import logical_actions
    for action in logical_actions.actions_for("ttr"):
        f = _field(tab, "ttr", 0, action)
        assert f.is_locked(), action
        assert f.property("locked") == "true", action
    # Locked fields never arm key capture.
    field = _field(tab, "ttr", 0, "book")
    QTest.mouseClick(field, Qt.LeftButton)
    assert field._awaiting is False
    # Alternate sets stay editable.
    alt = _field(tab, "ttr", 1, "book")
    assert not alt.is_locked()
    # The Default card's hint explains the lock.
    card = tab._entries_by_game["ttr"][0]["card"]
    from PySide6.QtWidgets import QLabel
    hint = [l for l in card.findChildren(QLabel) if l.objectName() == "set_body_hint"]
    assert hint and "detected" in hint[0].text().lower()


def test_default_locked_by_cached_detection(qapp, tmp_path, monkeypatch):
    # settings.json momentarily unreadable but a cached detection exists:
    # startup re-applies the cache, so hand edits would be silently lost.
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    settings = _FakeSettings(last_detected_keymap={"forward": "arrow_up"})
    tab = _make_tab(mgr, settings=settings)
    assert _field(tab, "ttr", 0, "book").is_locked()


def test_cc_default_locked_when_preferences_found(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    import services.wine_runtimes as wine_runtimes
    import utils.cc_settings as cc_settings
    monkeypatch.setattr(wine_runtimes, "discover_cc_installs", lambda: [object()])
    monkeypatch.setattr(cc_settings, "locate_cc_preferences",
                        lambda install: tmp_path / "preferences.json")
    mgr = _make_manager(tmp_path)
    tab = _make_tab(mgr)
    assert _field(tab, "cc", 0, "book").is_locked()
    assert not _field(tab, "ttr", 0, "book").is_locked()


def test_locked_default_rejects_key_change(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    import utils.ttr_settings as ttr_settings
    monkeypatch.setattr(ttr_settings, "locate_settings_file",
                        lambda engine_dir=None: "/fake/settings.json")
    mgr = _make_manager(tmp_path)
    before = mgr.get_key_for_action("ttr", 0, "book")
    tab = _make_tab(mgr)
    tab._on_key_changed_for_game("ttr", 0, "book", "F12")
    assert mgr.get_key_for_action("ttr", 0, "book") == before


def test_unlocked_default_accepts_key_change(qapp, tmp_path, monkeypatch):
    _patch_no_configs(monkeypatch)
    mgr = _make_manager(tmp_path)
    tab = _make_tab(mgr)
    tab._on_key_changed_for_game("ttr", 0, "book", "F12")
    assert mgr.get_key_for_action("ttr", 0, "book") == "F12"


def test_locked_field_in_conflict_still_paints_red(qapp, tmp_path, monkeypatch):
    # A locked Default binding can still collide with an alternate set's
    # binding; the red marker must not be suppressed by the lock styling.
    _patch_no_configs(monkeypatch)
    import utils.ttr_settings as ttr_settings
    monkeypatch.setattr(ttr_settings, "locate_settings_file",
                        lambda engine_dir=None: "/fake/settings.json")
    mgr = _make_manager(tmp_path)
    mgr.update_set_key("ttr", 0, "book", "Alt_L")
    mgr.add_set("ttr")
    mgr.update_set_key("ttr", 1, "jump", "Alt_L")
    tab = _make_tab(mgr)
    book = _field(tab, "ttr", 0, "book")
    assert book.is_locked()
    assert book.property("conflict") == "true"
