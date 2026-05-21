"""Tests for the PickerChip helper that generates chip QSS and inline HTML."""

from utils.widgets.picker_card import PickerChip


def test_qss_background_returns_gradient_string_for_known_slug():
    qss = PickerChip.qss_background("wine")
    assert "qlineargradient" in qss
    assert "#d04545" in qss


def test_qss_background_unknown_slug_falls_back():
    qss = PickerChip.qss_background("definitely-not-real")
    assert "qlineargradient" in qss
    assert "#4b5563" in qss or "#6a7280" in qss


def test_inline_html_contains_label_and_gradient_start_color():
    """QLabel rich-text doesn't support gradients, so the inline HTML chip
    uses the gradient's START color as a solid background. The end color is
    intentionally NOT in the output."""
    html = PickerChip.inline_html("bottles")
    assert "BOTTLES" in html
    assert "#9b6be0" in html  # gradient start
    assert "background-color:#9b6be0" in html


def test_inline_html_does_not_use_unsupported_qlineargradient():
    """Regression guard: QLabel's rich-text subset silently drops
    `qlineargradient(...)` and `linear-gradient(...)`, so the chip would
    render with no background at all. Must use a solid `background-color:`
    instead."""
    html = PickerChip.inline_html("wine")
    assert "qlineargradient" not in html
    assert "linear-gradient" not in html


def test_inline_html_uses_uppercase_label_even_for_unknown_slug():
    """Unknown slugs are uppercased (matches the chip_label fallback)."""
    html = PickerChip.inline_html("zzz-future")
    assert "ZZZ-FUTURE" in html


def test_inline_html_height_can_be_overridden():
    html = PickerChip.inline_html("wine", height_px=22)
    assert "22" in html
