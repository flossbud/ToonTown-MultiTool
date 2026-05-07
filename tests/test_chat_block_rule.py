"""Tests for the chat-aware key-block resolver table.

Rule (from spec):
- TTR has a letter hotkey  -> chat-off blocks {Return, Escape}
- TTR has no letter hotkey  -> chat-off blocks {Return, Escape} u a-z
- explicit chat-by-typing flag in settings.json overrides above

This file covers the resolver table only. Wiring of the resolver into the
input service constructor is covered by the existing input-service lifecycle
tests, which still pass via the legacy lambda fallback.
"""
import json
import pytest
from utils.ttr_settings import parse_ttr_settings, resolve_chat_block_list


@pytest.mark.parametrize(
    "controls,extras,expect_letters_blocked",
    [
        pytest.param({"forward": "w"}, None, False, id="letter-hotkey-no-letter-block"),
        pytest.param({"forward": "up", "reverse": "down"}, None, True, id="arrow-keys-letters-blocked"),
        pytest.param({"forward": "up"}, {"chat-by-typing": False}, False, id="explicit-flag-off-overrides-arrows"),
        pytest.param({"forward": "w"}, {"chat-by-typing": True}, True, id="explicit-flag-on-overrides-letters"),
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
