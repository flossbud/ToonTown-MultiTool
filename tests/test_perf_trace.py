import os
import importlib
import pytest


@pytest.fixture
def pt(monkeypatch, tmp_path):
    # Route the log into a temp dir and import fresh.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    import utils.perf_trace as pt
    importlib.reload(pt)
    return pt


def test_disabled_is_noop(pt, monkeypatch, tmp_path):
    monkeypatch.delenv("TTMT_PERF_TRACE", raising=False)
    assert pt.is_enabled() is False
    gid = pt.begin_gesture("tab_switch")
    with pt.perf_span("outgoing.grab", gid):
        pass
    pt.mark("statechange_fires", gid, 3)
    pt.flush()
    # No log file is created when disabled.
    assert not os.path.exists(pt.log_path())


def test_enabled_records_and_flushes(pt, monkeypatch):
    monkeypatch.setenv("TTMT_PERF_TRACE", "1")
    assert pt.is_enabled() is True
    gid = pt.begin_gesture("tab_switch")
    assert gid == "tab_switch#1"
    with pt.perf_span("incoming.grab", gid):
        pass
    pt.flush()
    text = open(pt.log_path()).read()
    assert "tab_switch#1 incoming.grab:" in text
    assert "ms" in text


def test_gesture_ids_increment_per_kind(pt, monkeypatch):
    monkeypatch.setenv("TTMT_PERF_TRACE", "1")
    assert pt.begin_gesture("tab_switch") == "tab_switch#1"
    assert pt.begin_gesture("tab_switch") == "tab_switch#2"
    assert pt.begin_gesture("window_state") == "window_state#1"


def test_flush_clears_buffer(pt, monkeypatch):
    monkeypatch.setenv("TTMT_PERF_TRACE", "1")
    gid = pt.begin_gesture("window_state")
    pt.mark("statechange_fires", gid, 2)
    pt.flush()
    pt.flush()  # second flush writes nothing new
    assert open(pt.log_path()).read().count("statechange_fires") == 1
