"""Lightweight, env-gated performance tracer for source-run profiling.

Active only when TTMT_PERF_TRACE=1. A true no-op otherwise: perf_span is a
null context and flush() does nothing, so the calls are safe to leave in
production code.

Spans are buffered in memory per gesture and written to disk only on flush(),
so no synchronous file I/O happens inside an animation/gesture hot path (which
would create the very jank we are measuring). Each line is tagged with a
gesture id (e.g. "tab_switch#12") so a gesture's substeps group together.

Log: $XDG_CACHE_HOME/toontown-multitool/perf_trace.log (or ~/.cache/...),
matching the faulthandler.log / inject_helper.log convention.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

# (gesture_id, label, value) tuples; value is milliseconds for spans or a raw
# number for mark(). Flushed and cleared by flush().
_buffer: list[tuple[str, str, float]] = []
_counters: dict[str, int] = {}


def is_enabled() -> bool:
    return os.environ.get("TTMT_PERF_TRACE") == "1"


def log_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "toontown-multitool", "perf_trace.log")


def begin_gesture(kind: str) -> str:
    """Return a fresh gesture id like 'tab_switch#3'."""
    n = _counters.get(kind, 0) + 1
    _counters[kind] = n
    return f"{kind}#{n}"


@contextmanager
def perf_span(label: str, gesture_id: str = ""):
    if not is_enabled():
        yield
        return
    start = time.perf_counter_ns()
    try:
        yield
    finally:
        ms = (time.perf_counter_ns() - start) / 1_000_000.0
        _buffer.append((gesture_id, label, ms))


def mark(label: str, gesture_id: str = "", value: float = 0.0) -> None:
    """Record a non-timed data point (e.g. a WindowStateChange fire count)."""
    if not is_enabled():
        return
    _buffer.append((gesture_id, label, float(value)))


def flush() -> None:
    """Write buffered spans to the log, then clear the buffer. No-op when
    disabled or the buffer is empty."""
    if not is_enabled() or not _buffer:
        return
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for gid, label, value in _buffer:
                prefix = f"{gid} " if gid else ""
                f.write(f"{prefix}{label}: {value:.2f} ms\n")
    except OSError:
        pass
    finally:
        _buffer.clear()
