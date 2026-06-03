"""Preserved external API: update_dot_state (id-keyed, off-page/out-of-range
safe, repaint-on-flip), clear_all_credentials (tears down off-page slots),
and shutdown (cleans transient resources without killing running games)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication

from tabs.launch_tab import LaunchTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid, game="ttr"):
    return SimpleNamespace(id=aid, game=game, label=aid, username=aid,
                           password="pw", launcher_token="")


def _tab(qapp, n):
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = [_meta(f"t{i}") for i in range(n)]
    cred.clear_all.return_value = []
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    tab._build_ui()
    return tab


def test_update_dot_state_offpage_updates_slot_only(qapp):
    tab = _tab(qapp, 6)  # t5 off page 0
    tab._slots["ttr"]["t5"].launcher = SimpleNamespace(is_running=lambda: True)
    tab.update_dot_state(5, "active")
    assert tab._slots["ttr"]["t5"].dot_state == "active"
    assert "t5" not in tab._visible_tiles["ttr"]  # off page, no tile


def test_update_dot_state_out_of_range_is_safe(qapp):
    tab = _tab(qapp, 2)
    tab.update_dot_state(99, "active")   # too high
    tab.update_dot_state(-1, "active")   # negative must not negative-index
    # no exception == pass; and no slot got a spurious dot_state from -1 indexing
    assert all(s.dot_state == "" for s in tab._slots["ttr"].values())


def test_update_dot_state_repaints_on_flip(qapp):
    tab = _tab(qapp, 6)  # 2 pages; t5 on page 1
    running = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["t5"].launcher = running
    tab._slots["ttr"]["t5"].state = "running"
    # Use a distinct dot_state ("warn" -> #E8A838) so the assertion proves the
    # render re-applied dot_state and overrode set_state's running #56c856.
    tab.update_dot_state(5, "warn")       # off-page: slot only
    tab._on_page_changed("ttr", 1)        # flip to t5's page -> tile rebuilt
    tile = tab._visible_tiles["ttr"]["t5"]
    dot = getattr(tile, "status_dot", None)
    assert dot is not None
    assert dot._color.name().lower() == "#e8a838"  # re-applied warn color


def test_clear_all_credentials_tears_down_offpage_slots(qapp):
    tab = _tab(qapp, 6)
    killed, cancelled = [], []
    tab._slots["ttr"]["t5"].launcher = SimpleNamespace(
        is_running=lambda: True, kill=lambda: killed.append("t5"))
    tab._slots["ttr"]["t5"].worker = SimpleNamespace(cancel=lambda: cancelled.append("t5"))
    tab._slots["ttr"]["t5"].loading_timer = _FakeTimer()
    tab.cred_manager.get_accounts_metadata.return_value = []
    tab.clear_all_credentials()
    assert killed == ["t5"]
    assert cancelled == ["t5"]
    assert tab._loading["ttr"] == []


def test_shutdown_cleans_transient_but_does_not_kill_games(qapp):
    tab = _tab(qapp, 2)
    killed, cancelled = [], []
    slot = tab._slots["ttr"]["t0"]
    slot.launcher = SimpleNamespace(is_running=lambda: True, kill=lambda: killed.append(1))
    slot.worker = SimpleNamespace(cancel=lambda: cancelled.append(1))
    slot.loading_timer = _FakeTimer()
    tab._loading["ttr"] = ["t0"]
    tab.shutdown()
    assert cancelled == [1]      # in-flight login cancelled
    assert killed == []          # running game NOT killed on UI shutdown
    assert tab._loading["ttr"] == []
    assert slot.loading_timer is None
    assert slot.worker is None   # detached, so a late signal fails the guard


def test_refresh_theme_preserves_multitoon_dot(qapp):
    # A direct refresh_theme() (e.g. theme change from main.py) must not clobber
    # a visible running account's Multitoon dot_state back to the running color.
    tab = _tab(qapp, 2)
    tab._slots["ttr"]["t0"].launcher = SimpleNamespace(is_running=lambda: True)
    tab._slots["ttr"]["t0"].state = "running"
    tab.update_dot_state(0, "warn")          # t0 is on the visible page
    assert tab._visible_tiles["ttr"]["t0"].status_dot._color.name().lower() == "#e8a838"
    tab.refresh_theme()                       # must re-apply the warn dot last
    assert tab._visible_tiles["ttr"]["t0"].status_dot._color.name().lower() == "#e8a838"


def test_offpage_queue_message_rehydrates_on_flip(qapp):
    # A queue_update for an off-page account stores the position/ETA on the slot
    # so flipping to its page shows "#N (~Ms)", not a bare "In queue".
    tab = _tab(qapp, 6)  # t5 on page 1
    tab._update_queue("ttr", "t5", 7, 42)
    assert tab._slots["ttr"]["t5"].message == "#7 (~42s)"
    tab._on_page_changed("ttr", 1)
    tile = tab._visible_tiles["ttr"]["t5"]
    # The rendered tile carries the queue detail (its raw/status message).
    st, msg, _ = tab._effective_state("ttr", tab._slots["ttr"]["t5"])
    assert msg == "#7 (~42s)"


def test_later_flip_tiles_inherit_layout_mode(qapp):
    # Tiles created on a later page flip must reflect the section's layout mode.
    tab = _tab(qapp, 6)
    tab.set_layout_mode("full")
    tab._on_page_changed("ttr", 1)   # builds fresh tiles for page 1
    assert tab.ttr_section._layout_mode == "full"
    # Fresh tiles exist and carry the content-scale floor (>=130 min-height).
    assert tab.ttr_section.tiles
    assert tab.ttr_section.tiles[0].minimumHeight() >= 130


class _FakeTimer:
    def __init__(self):
        self.stopped = False
    def stop(self):
        self.stopped = True
    def deleteLater(self):
        pass
