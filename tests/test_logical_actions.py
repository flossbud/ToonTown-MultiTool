"""Unit tests for the logical action registry."""

from utils import logical_actions


class TestSupports:
    def test_shared_action_supports_both_games(self):
        assert logical_actions.supports("ttr", "forward") is True
        assert logical_actions.supports("cc", "forward") is True

    def test_cc_only_action_supports_cc_only(self):
        assert logical_actions.supports("cc", "sprint") is True
        assert logical_actions.supports("ttr", "sprint") is False

    def test_unknown_action(self):
        assert logical_actions.supports("ttr", "nonexistent") is False

    def test_unknown_game(self):
        assert logical_actions.supports("xyz", "forward") is False


class TestDefaultKey:
    def test_shared_action_has_per_game_default(self):
        assert logical_actions.default_key("ttr", "forward") == "w"
        assert logical_actions.default_key("cc", "forward") == "w"

    def test_book_default_differs_per_game(self):
        assert logical_actions.default_key("ttr", "book") == "Alt_L"
        assert logical_actions.default_key("cc", "book") == "Escape"

    def test_sprint_default_for_cc_only(self):
        assert logical_actions.default_key("cc", "sprint") == "Shift_L"
        assert logical_actions.default_key("ttr", "sprint") is None

    def test_unknown_action_returns_none(self):
        assert logical_actions.default_key("ttr", "fly") is None


class TestActionsFor:
    def test_ttr_has_nine_actions(self):
        actions = set(logical_actions.actions_for("ttr"))
        assert actions == {
            "forward", "reverse", "left", "right",
            "jump", "book", "gags", "tasks", "map",
        }

    def test_cc_has_ten_actions(self):
        actions = set(logical_actions.actions_for("cc"))
        assert actions == {
            "forward", "reverse", "left", "right",
            "jump", "book", "gags", "tasks", "map",
            "sprint",
        }

    def test_actions_for_unknown_game_is_empty(self):
        assert logical_actions.actions_for("xyz") == []
