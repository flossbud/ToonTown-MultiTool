"""Unit tests for utils.shared_widgets.repolish.

repolish() guards a PySide6/Shiboken quirk seen in frozen macOS builds where
widget.style() intermittently returns a miscached wrapper (a QWidgetItem)
instead of the QStyle, which would crash on .unpolish(). These tests pin both
paths deterministically with mocks, so no Qt or display is needed.
"""

from unittest.mock import MagicMock

from utils.shared_widgets import repolish


def test_repolish_normal_style_unpolishes_and_polishes():
    """When style() returns a real QStyle-like object, repolish runs the
    full unpolish/polish/update dance against the widget."""
    style = MagicMock()  # has unpolish + polish
    widget = MagicMock()
    widget.style.return_value = style

    repolish(widget)

    style.unpolish.assert_called_once_with(widget)
    style.polish.assert_called_once_with(widget)
    widget.update.assert_called_once_with()


def test_repolish_miscached_style_skips_without_crashing():
    """When style() returns a miscached non-QStyle (no unpolish attribute,
    e.g. a QWidgetItem), repolish must not raise; it still calls update()."""

    class FakeWidgetItem:
        """Stand-in for the miscached QWidgetItem: no unpolish/polish."""

    widget = MagicMock()
    widget.style.return_value = FakeWidgetItem()

    # Must not raise (the bug crashed here with AttributeError).
    repolish(widget)

    widget.update.assert_called_once_with()


def test_repolish_partial_style_missing_polish_is_skipped():
    """Defensive: an object with unpolish but not polish is still treated as
    not-a-style and skipped, rather than half-applying."""
    style = MagicMock(spec=["unpolish"])  # has unpolish, no polish
    widget = MagicMock()
    widget.style.return_value = style

    repolish(widget)

    style.unpolish.assert_not_called()
    widget.update.assert_called_once_with()
