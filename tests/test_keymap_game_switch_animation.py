"""Covers the push_slide_pages animation wiring in _on_segment_clicked."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    def __init__(self):
        self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
    def get(self, k, default=None):
        return self._d.get(k, default)
    def set(self, k, v):
        self._d[k] = v
    def on_change(self, cb):
        pass


class _FakeCredManager:
    def get_accounts_metadata(self, game=None):
        return []
    def on_change(self, cb):
        pass


def _make_tab(qapp, monkeypatch):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager
    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: True)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: True)
    return KeymapTab(
        KeymapManager(),
        settings_manager=_FakeSettings(),
        credentials_manager=_FakeCredManager(),
    )


def test_segment_click_calls_push_slide_pages(qapp, monkeypatch):
    """Switching from TTR to CC must call push_slide_pages with (stack, 0, 1, axis='h')."""
    tab = _make_tab(qapp, monkeypatch)
    calls = []
    def fake_push(stack, from_idx, to_idx, axis="h"):
        calls.append((stack, from_idx, to_idx, axis))
        stack.setCurrentIndex(to_idx)
        return None
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages", fake_push)
    tab._on_segment_clicked("cc")
    assert len(calls) == 1
    stack, from_idx, to_idx, axis = calls[0]
    assert stack is tab._game_stack
    assert from_idx == 0
    assert to_idx == 1
    assert axis == "h"


def test_segment_click_back_calls_push_slide_pages_reverse(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    tab._active_game = "cc"
    tab._game_stack.setCurrentIndex(1)
    calls = []
    def fake_push(stack, from_idx, to_idx, axis="h"):
        calls.append((from_idx, to_idx))
        stack.setCurrentIndex(to_idx)
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages", fake_push)
    tab._on_segment_clicked("ttr")
    assert calls == [(1, 0)]


def test_segment_click_updates_active_game(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages",
                        lambda s, f, t, axis="h": s.setCurrentIndex(t))
    tab._on_segment_clicked("cc")
    assert tab._active_game == "cc"


def test_segment_click_same_game_is_noop(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    calls = []
    monkeypatch.setattr("tabs.keymap_tab.push_slide_pages",
                        lambda s, f, t, axis="h": calls.append("called"))
    tab._on_segment_clicked("ttr")  # already on TTR
    assert calls == []


def test_segment_click_under_reduced_motion(qapp, monkeypatch):
    """When motion is reduced, push_slide_pages snaps the index and returns
    None. We still expect the call to happen - push_slide_pages itself
    handles the reduced-motion branch, not _on_segment_clicked."""
    tab = _make_tab(qapp, monkeypatch)
    monkeypatch.setattr("utils.motion.is_reduced", lambda: True)
    tab._on_segment_clicked("cc")
    # Stack must have snapped to the CC index even without animation.
    assert tab._game_stack.currentIndex() == 1
    assert tab._active_game == "cc"
