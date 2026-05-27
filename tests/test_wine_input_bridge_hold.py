"""Backend-level hold-shape tests for the Wine input bridge.

Verifies send_to_window(..., 'keydown', ...) followed by send_to_window
(..., 'keyup', ...) produces two distinct framed TCP messages to the
bridge ('down' op and 'up' op). Mocks the bridge resolution seam so the
test runs without a Wine prefix.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

from utils import wine_input_bridge


def _install_fake_bridge(monkeypatch, sent_ops):
    """Replace the bridge resolution seam used by send_to_window with a
    stub that records send() calls. Returns the fake bridge.

    send_to_window's pipeline is:
      1. resolve PID via GameRegistry._get_host_pid_for_window_xres, then
         x11_discovery.get_window_pid as fallback
      2. resolve bridge via _bridge_for_pid(pid)
      3. cross_check_sort_order against window_ids
      4. compute active_index via x11_discovery.get_active_window_id
      5. dispatch on action -> bridge.send(op, index, keysym, active_index)

    We mock the smallest set of seams to reach step 5 deterministically:
    a fake bridge swapped in at _bridge_for_pid, plus the two
    x11_discovery helpers so we don't touch the live X server.
    """

    class _FakeBridge:
        def send(self, op, index, keysym, active_index=-1):
            sent_ops.append((op, index, keysym, active_index))
            return True

        def cross_check_sort_order(self, window_ids):
            return True

    fake_bridge = _FakeBridge()
    monkeypatch.setattr(
        wine_input_bridge.x11_discovery, "get_window_pid", lambda wid: 123
    )
    monkeypatch.setattr(
        wine_input_bridge.x11_discovery, "get_active_window_id", lambda: "100"
    )
    monkeypatch.setattr(wine_input_bridge, "_bridge_for_pid", lambda pid: fake_bridge)
    return fake_bridge


def test_send_to_window_keydown_then_keyup_produces_two_distinct_ops(monkeypatch):
    sent_ops = []
    _install_fake_bridge(monkeypatch, sent_ops)
    from utils.wine_input_bridge import send_to_window

    ok1 = send_to_window("100", ["100", "200"], "keydown", "Delete", None)
    ok2 = send_to_window("100", ["100", "200"], "keyup", "Delete", None)
    assert ok1 is True and ok2 is True
    ops = [op for op, _, _, _ in sent_ops]
    assert ops == ["down", "up"], (
        f"expected ['down', 'up'] from keydown/keyup pair, got {ops}"
    )


def test_send_to_window_keydown_uses_down_op(monkeypatch):
    sent_ops = []
    _install_fake_bridge(monkeypatch, sent_ops)
    from utils.wine_input_bridge import send_to_window

    send_to_window("100", ["100", "200"], "keydown", "space", None)
    assert len(sent_ops) == 1
    assert sent_ops[0][0] == "down"
    assert sent_ops[0][2] == "space"


def test_send_to_window_keyup_uses_up_op(monkeypatch):
    sent_ops = []
    _install_fake_bridge(monkeypatch, sent_ops)
    from utils.wine_input_bridge import send_to_window

    send_to_window("100", ["100", "200"], "keyup", "space", None)
    assert len(sent_ops) == 1
    assert sent_ops[0][0] == "up"
    assert sent_ops[0][2] == "space"
