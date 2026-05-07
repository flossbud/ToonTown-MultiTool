"""Tests for the chat-aware key-block rule wired into input_service.

Rule (from spec):
- TTR has a letter hotkey  -> chat-off blocks {Return, Escape}
- TTR has no letter hotkey  -> chat-off blocks {Return, Escape} u a-z
- explicit chat-by-typing flag in settings.json overrides above
"""
import json
import pytest
from utils.ttr_settings import parse_ttr_settings, resolve_chat_block_list


@pytest.mark.parametrize(
    "controls,extras,expect_letters_blocked",
    [
        ({"forward": "w"}, None, False),
        ({"forward": "up", "reverse": "down"}, None, True),
        ({"forward": "up"}, {"chat-by-typing": False}, False),
        ({"forward": "w"}, {"chat-by-typing": True}, True),
    ],
)
def test_chat_block_rule_table(tmp_path, controls, extras, expect_letters_blocked):
    payload = {"controls": controls}
    if extras:
        payload.update(extras)
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(payload))
    s = parse_ttr_settings(p)
    block = resolve_chat_block_list(s)
    assert "Return" in block
    if expect_letters_blocked:
        assert "a" in block and "m" in block and "z" in block
    else:
        assert "a" not in block and "m" not in block and "z" not in block
