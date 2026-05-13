"""Pins H_FULL after the chip-rail redesign — bumped from 800 to 852 so the
full UI content budget (852 − 56 header − 52 chip rail = 744) matches today's
budget (800 − 56 = 744), leaving _FullToonCard reference rects untouched."""

from main import H_FULL, W_FULL


def test_h_full_is_852_for_chip_rail_chrome():
    assert H_FULL == 852


def test_w_full_unchanged_at_1280():
    assert W_FULL == 1280
