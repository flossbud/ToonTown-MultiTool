"""Cross-platform unit tests for _RemoteDelivery's correlation-id read logic.

The id-validation (discard a stale/late reply from a prior timed-out request, never
misreport it as the current reply) is PURE Python and guards a real desync bug, so it
must run on ALL platforms' CI - NOT gated behind a macOS skip. The module imports cleanly
off-macOS (its PyObjC use is lazy/optional), and `_recv_matching` is driven through an
injectable line-reader, so no real helper or macOS framework is needed.
"""
import json

import utils.macos_inject_remote as rem


def _bare():
    """A _RemoteDelivery with __init__ (and its spawn) bypassed - only `_recv_matching`,
    which is pure, is exercised."""
    return rem._RemoteDelivery.__new__(rem._RemoteDelivery)


def test_recv_matching_discards_stale_reply():
    d = _bare()
    awaited = 42
    lines = [
        json.dumps({"ok": True, "id": 7, "stale": True}),       # late reply for a prior req
        json.dumps({"ok": True, "id": awaited, "psn": "ab"}),   # the one we awaited
    ]
    it = iter(lines)

    def fake_read_line(remaining):
        assert remaining > 0
        return next(it, None)

    reply = d._recv_matching(awaited, fake_read_line, timeout=5.0)
    assert reply is not None
    assert reply.get("id") == awaited
    assert reply.get("psn") == "ab"


def test_recv_matching_none_when_only_stale_then_eof():
    d = _bare()
    it = iter([json.dumps({"ok": True, "id": 1}), None])  # stale, then EOF/timeout

    def fake_read_line(remaining):
        return next(it, None)

    # Never return the stale reply; signal None instead of misreporting it as ours.
    assert d._recv_matching(99, fake_read_line, timeout=5.0) is None


def test_recv_matching_skips_unparseable_lines():
    d = _bare()
    it = iter(['{"op":', "[1, 2, 3]", json.dumps({"ok": True, "id": 5})])  # bad json, non-dict, ours

    def fake_read_line(remaining):
        return next(it, None)

    reply = d._recv_matching(5, fake_read_line, timeout=5.0)
    assert reply is not None and reply.get("id") == 5
