"""manual_refresh() coalesces requests that arrive within _REFRESH_COOLDOWN_S of
the last accepted refresh, so a held/mashed F5 (or rapid Refresh clicks) cannot
fire back-to-back heavy InputService restarts. The decision logic lives in the
pure helper _refresh_is_coalesced(now), tested here without the heavy __init__."""
from __future__ import annotations

from tabs.multitoon._tab import MultitoonTab


def _tab():
    # Bypass the heavy __init__; set only what the cooldown helper reads, mirroring
    # the real __init__ default (-inf so the very first refresh is always accepted,
    # even when time.monotonic() is small near process start).
    tab = MultitoonTab.__new__(MultitoonTab)
    tab._last_refresh_monotonic = float("-inf")
    return tab


def test_first_request_is_accepted():
    tab = _tab()
    assert tab._refresh_is_coalesced(100.0) is False


def test_first_request_at_low_monotonic_is_accepted():
    # Regression: a 0.0 default would coalesce a first refresh when monotonic()
    # is below the cooldown; the -inf default must accept it.
    tab = _tab()
    assert tab._refresh_is_coalesced(0.1) is False


def test_second_request_within_window_is_coalesced():
    tab = _tab()
    assert tab._refresh_is_coalesced(100.0) is False
    assert tab._refresh_is_coalesced(100.0 + MultitoonTab._REFRESH_COOLDOWN_S - 0.1) is True


def test_request_after_window_is_accepted():
    tab = _tab()
    assert tab._refresh_is_coalesced(100.0) is False
    assert tab._refresh_is_coalesced(100.0 + MultitoonTab._REFRESH_COOLDOWN_S + 0.1) is False


def test_accepted_request_advances_the_window():
    tab = _tab()
    assert tab._refresh_is_coalesced(100.0) is False
    assert tab._refresh_is_coalesced(102.0) is False          # past window -> accepted
    assert tab._refresh_is_coalesced(102.5) is True           # within window of 102.0


def test_manual_refresh_returns_early_when_coalesced(monkeypatch):
    # Guards against the helper not being wired into manual_refresh: when coalesced,
    # the heavy path (invalidate_port_to_wid_cache and everything after) must NOT run.
    import tabs.multitoon._tab as mod
    tab = _tab()
    logs = []
    monkeypatch.setattr(tab, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr(tab, "_refresh_is_coalesced", lambda now: True)
    monkeypatch.setattr(mod, "invalidate_port_to_wid_cache",
                        lambda: (_ for _ in ()).throw(AssertionError("heavy path ran")))
    tab.manual_refresh()
    assert any("coalesced" in m for m in logs)
