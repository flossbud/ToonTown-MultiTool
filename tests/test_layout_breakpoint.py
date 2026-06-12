"""Tests for the window-size → layout-mode state machine in MultiToonTool."""

import pytest


# Pure function under test — extracted out of MultiToonTool so we can test
# without instantiating Qt windows.
from main import _decide_layout_mode, W_FULL, H_FULL, DEADBAND_W, DEADBAND_H


def test_decide_starts_compact_at_default_size():
    assert _decide_layout_mode("compact", 560, 650) == "compact"


def test_decide_swaps_to_full_above_breakpoint_plus_deadband():
    assert _decide_layout_mode("compact", W_FULL + DEADBAND_W, H_FULL + DEADBAND_H) == "full"


def test_decide_stays_compact_just_above_breakpoint_within_deadband():
    """Hysteresis: 1280-wide window stays compact because the 'enter Full' threshold is 1360."""
    assert _decide_layout_mode("compact", W_FULL, H_FULL) == "compact"
    assert _decide_layout_mode("compact", W_FULL + DEADBAND_W - 1, H_FULL + DEADBAND_H) == "compact"


def test_decide_stays_full_when_dragging_back_into_deadband():
    """Once in Full, stay there until well below the breakpoint."""
    assert _decide_layout_mode("full", W_FULL + 1, H_FULL + 1) == "full"
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W + 1, H_FULL) == "full"


def test_decide_swaps_back_to_compact_below_breakpoint_minus_deadband():
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W, H_FULL - DEADBAND_H) == "compact"


def test_decide_swaps_to_compact_when_either_dimension_drops():
    """Either dimension below the deadband triggers Compact — not both."""
    # Width drops, height stays high
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W, H_FULL + 100) == "compact"
    # Height drops, width stays high
    assert _decide_layout_mode("full", W_FULL + 100, H_FULL - DEADBAND_H) == "compact"


def test_main_set_layout_mode_propagates_to_tabs():
    """When main._set_layout_mode flips modes, every mode-aware tab is updated."""
    from unittest.mock import MagicMock
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance._layout_mode = "compact"
    instance.customization_overlay = None
    instance.multitoon_tab = MagicMock()
    instance.launch_tab = MagicMock()
    instance.settings_tab = MagicMock()
    MultiToonTool._set_layout_mode(instance, "full")
    instance.multitoon_tab.set_layout_mode.assert_called_once_with("full")
    instance.launch_tab.set_layout_mode.assert_called_once_with("full")
    instance.settings_tab.set_layout_mode.assert_called_once_with("full")
    assert instance._layout_mode == "full"


def test_main_resume_pending_mode_swap_propagates_to_tabs():
    """The deferred-swap resume path drives the same tab contract."""
    from unittest.mock import MagicMock
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance._layout_mode = "compact"
    instance._pending_mode_swap = "full"
    instance.multitoon_tab = MagicMock()
    instance.launch_tab = MagicMock()
    instance.settings_tab = MagicMock()
    MultiToonTool._resume_pending_mode_swap(instance)
    instance.multitoon_tab.set_layout_mode.assert_called_once_with("full")
    instance.launch_tab.set_layout_mode.assert_called_once_with("full")
    instance.settings_tab.set_layout_mode.assert_called_once_with("full")
    assert instance._layout_mode == "full"
