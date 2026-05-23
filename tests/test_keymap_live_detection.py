"""Covers KeymapTab's live-detection refresh: sub-rail show/hide and
page-validity swaps in response to settings + credentials changes."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    """SettingsManager stand-in with a working on_change registration."""
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


class _FakeCredManager:
    """CredentialsManager stand-in with a working on_change registration
    and mutable account counts."""
    def __init__(self, ttr=0, cc=0):
        self._ttr_count = ttr
        self._cc_count = cc
        self._callbacks: list = []
    def get_accounts_metadata(self, game=None):
        if game == "ttr":
            return [object()] * self._ttr_count
        if game == "cc":
            return [object()] * self._cc_count
        return [object()] * (self._ttr_count + self._cc_count)
    def on_change(self, cb):
        self._callbacks.append(cb)
    def add(self, game):
        if game == "ttr":
            self._ttr_count += 1
        else:
            self._cc_count += 1
        for cb in self._callbacks:
            cb()
    def remove(self, game):
        if game == "ttr":
            self._ttr_count = max(0, self._ttr_count - 1)
        else:
            self._cc_count = max(0, self._cc_count - 1)
        for cb in self._callbacks:
            cb()


def _make_tab(qapp, monkeypatch, *, ttr=False, cc=False, cred_manager=None):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager
    if cred_manager is None:
        cred_manager = _FakeCredManager()
    settings = _FakeSettings()
    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: ttr)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: cc)
    tab = KeymapTab(
        KeymapManager(),
        settings_manager=settings,
        credentials_manager=cred_manager,
    )
    return tab, settings, cred_manager


def test_subrail_hidden_when_one_active(qapp, monkeypatch):
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False)
    # Sub-rail either was never built, or is built but hidden.
    # Use isHidden() - isVisible() is always False for unshown top-level windows.
    assert tab._segmented is None or tab._segmented.isHidden() is True
    assert tab._active_game == "ttr"


def test_subrail_visible_when_both_active(qapp, monkeypatch):
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=True)
    assert tab._segmented is not None
    assert tab._segmented.isHidden() is False


def test_subrail_appears_on_settings_change(qapp, monkeypatch):
    """Start with TTR only. Adding cc_engine_dir should reveal the sub-rail."""
    tab, settings, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False)
    assert tab._segmented is None or tab._segmented.isHidden()
    # Flip _cc_detected to True (mirrors the user editing the path in Settings).
    monkeypatch.setattr(type(tab), "_cc_detected", lambda self: True)
    settings.set("cc_engine_dir", "/some/path")  # fires on_change(key, value)
    assert tab._segmented is not None
    assert tab._segmented.isHidden() is False


def test_subrail_appears_on_account_added(qapp, monkeypatch):
    """Start with TTR install only and no accounts. Adding a CC account
    should reveal the sub-rail (the account presence makes CC 'active')."""
    cred = _FakeCredManager()
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False, cred_manager=cred)
    assert tab._segmented is None or tab._segmented.isHidden()
    cred.add("cc")  # fires on_change()
    assert tab._segmented is not None
    assert tab._segmented.isHidden() is False


def test_subrail_disappears_when_one_active(qapp, monkeypatch):
    """Start with both, simulate CC being removed. Sub-rail hides."""
    cred = _FakeCredManager(cc=1)
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False, cred_manager=cred)
    assert tab._segmented.isHidden() is False
    cred.remove("cc")
    assert tab._segmented.isHidden() is True


def test_animates_away_from_removed_game(qapp, monkeypatch):
    """If currently on CC and CC becomes inactive, animate back to TTR."""
    cred = _FakeCredManager(cc=1)
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False, cred_manager=cred)
    # Switch to CC first (snap, not animated, by directly setting state).
    tab._active_game = "cc"
    tab._game_stack.setCurrentIndex(1)
    calls = []
    def fake_push(stack, from_idx, to_idx, axis="h"):
        calls.append((from_idx, to_idx))
        stack.setCurrentIndex(to_idx)
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages", fake_push)
    cred.remove("cc")
    assert calls == [(1, 0)]
    assert tab._active_game == "ttr"
    assert tab._game_stack.currentIndex() == 0


def test_refresh_visibility_short_circuits_when_no_change(qapp, monkeypatch):
    """A no-op _emit_change (e.g., a rename) should not trigger a slide."""
    cred = _FakeCredManager(cc=1)
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False, cred_manager=cred)
    calls = []
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages",
                        lambda s, f, t, axis="h": calls.append("animated"))
    # Trigger a callback fire without actually changing active set: add then remove same game in one tick.
    cred.add("ttr")  # ttr stays active (already active via install)
    assert calls == []  # active set unchanged


def test_subrail_rebuilds_only_once(qapp, monkeypatch):
    """Going 1 -> 2 -> 1 -> 2 should only construct the sub-rail once.
    Visibility toggles thereafter."""
    cred = _FakeCredManager()
    tab, _, _ = _make_tab(qapp, monkeypatch, ttr=True, cc=False, cred_manager=cred)
    assert tab._segmented is None
    cred.add("cc")  # 1 -> 2
    first_subrail = tab._segmented
    assert first_subrail is not None
    cred.remove("cc")  # 2 -> 1
    assert tab._segmented is first_subrail  # not destroyed
    assert first_subrail.isHidden() is True
    cred.add("cc")  # 1 -> 2 again
    assert tab._segmented is first_subrail  # same widget
    assert first_subrail.isHidden() is False
