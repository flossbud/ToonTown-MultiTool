import importlib.util
import pathlib
import sys

import pytest

_SPIKE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "macos_mouse_spike.py"
_spec = importlib.util.spec_from_file_location("macos_mouse_spike", _SPIKE)
spike = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = spike
_spec.loader.exec_module(spike)


def test_content_rect_zero_inset_is_identity():
    assert spike.content_rect((10, 20, 800, 600), 0) == (10, 20, 800, 600)


def test_content_rect_subtracts_top_inset():
    # A 28pt title bar shifts the content origin down and shrinks the height.
    assert spike.content_rect((10, 20, 800, 600), 28) == (10, 48, 800, 572)


def test_content_rect_never_negative_height():
    # A pathological inset larger than the frame clamps height to 0, never negative.
    assert spike.content_rect((0, 0, 100, 20), 50) == (0, 50, 100, 0)


def test_content_point_to_global_corners_and_center():
    frame = (100, 200, 800, 600)  # inset 0 -> content == frame
    assert spike.content_point_to_global((0.0, 0.0), frame, 0) == (100.0, 200.0)
    assert spike.content_point_to_global((1.0, 1.0), frame, 0) == (900.0, 800.0)
    assert spike.content_point_to_global((0.5, 0.5), frame, 0) == (500.0, 500.0)


def test_content_point_to_global_respects_inset():
    frame = (0, 0, 200, 120)
    # inset 20 -> content (0,20,200,100); center maps to (100, 70).
    assert spike.content_point_to_global((0.5, 0.5), frame, 20) == (100.0, 70.0)
