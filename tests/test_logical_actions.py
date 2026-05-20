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
        assert logical_actions.default_key("ttr", "forward") == "Up"
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

    def test_ttr_action_order_is_stable(self):
        assert logical_actions.actions_for("ttr") == [
            "forward", "reverse", "left", "right",
            "jump", "book", "gags", "tasks", "map",
        ]

    def test_cc_action_order_is_stable(self):
        assert logical_actions.actions_for("cc") == [
            "forward", "reverse", "left", "right",
            "jump", "book", "gags", "tasks", "map",
            "sprint",
        ]

    def test_actions_for_unknown_game_is_empty(self):
        assert logical_actions.actions_for("xyz") == []


class TestTtrMovementDefaults:
    """TTR fresh-install ships arrow keys for movement, not WASD.
    The registry is the source of truth for the legacy routing fallback,
    so getting this wrong breaks _resolve_logical_action for the typical
    TTR user."""

    def test_forward_default_is_up(self):
        assert logical_actions.default_key("ttr", "forward") == "Up"

    def test_reverse_default_is_down(self):
        assert logical_actions.default_key("ttr", "reverse") == "Down"

    def test_left_default_is_left(self):
        assert logical_actions.default_key("ttr", "left") == "Left"

    def test_right_default_is_right(self):
        assert logical_actions.default_key("ttr", "right") == "Right"

    def test_cc_movement_defaults_unchanged(self):
        # CC defaults are WASD (the canonical we lock prefs to). Regression
        # guard so a future edit doesn't break the CC side while fixing TTR.
        assert logical_actions.default_key("cc", "forward") == "w"
        assert logical_actions.default_key("cc", "reverse") == "s"
        assert logical_actions.default_key("cc", "left") == "a"
        assert logical_actions.default_key("cc", "right") == "d"
