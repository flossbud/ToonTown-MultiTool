"""Env-gated diagnostic trace for the input / movement-grabber pipeline.

Enable by setting TTMT_INPUT_TRACE=1 before launching the app. One line per
event is appended to TTMT_INPUT_TRACE_FILE (default /tmp/ttmt-input-trace.log),
each tagged with a millisecond timestamp. Completely inert when the env var is
unset (the module-level flag short-circuits) and never raises.

This exists to capture an actual runtime event trace at the grabber and
InputService boundaries when a bug cannot be reproduced from code alone.
"""
from __future__ import annotations

import os
import time

ENABLED = bool(os.environ.get("TTMT_INPUT_TRACE"))
_PATH = os.environ.get("TTMT_INPUT_TRACE_FILE", "/tmp/ttmt-input-trace.log")
_t0 = time.monotonic()


def trace(tag: str, msg: str) -> None:
    """Append one trace line. No-op unless TTMT_INPUT_TRACE is set."""
    if not ENABLED:
        return
    try:
        line = f"{(time.monotonic() - _t0) * 1000:10.1f}ms [{tag}] {msg}\n"
        with open(_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass
