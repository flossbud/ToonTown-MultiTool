"""Tests for utils.motion."""

from __future__ import annotations


def test_reduced_motion_returns_bool():
    from utils.motion import reduced_motion_enabled
    result = reduced_motion_enabled()
    assert isinstance(result, bool)


def test_reduced_motion_default_is_false():
    """Until the OS-level read is plumbed (follow-up), the helper
    returns False so animations remain on by default."""
    from utils.motion import reduced_motion_enabled
    assert reduced_motion_enabled() is False
