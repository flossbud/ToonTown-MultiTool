"""Unit tests for the _CardStripe widget that animates the per-toon card
top stripe in the Multitoon compact UI."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def stripe(qapp):
    """Fresh _CardStripe widget per test."""
    from tabs.multitoon._compact_layout import _CardStripe
    parent = QWidget()
    parent.resize(400, 50)
    s = _CardStripe(parent)
    s.resize(400, 3)
    return s


def _grey():
    return QColor("#555555")


def _ttr_full():
    return QColor("#4A8FE7")


def _ttr_muted(qapp):
    from tabs.multitoon._compact_layout import _muted_brand
    return _muted_brand(_ttr_full())


def _settle(stripe):
    """Skip the in-flight animation to its end so finished handlers fire."""
    if stripe._anim is not None:
        stripe._anim.setCurrentTime(stripe._anim.duration())


def test_stripe_starts_uninitialised(stripe):
    """A fresh stripe has no color yet (first set_color seeds it)."""
    assert stripe._anim is None
    assert stripe._prev_color is None


def test_first_set_color_seeds_without_animation(stripe):
    """The very first set_color sets _color directly with no animation -
    there's no prior state to fill from."""
    stripe.set_color(_grey())
    assert stripe._color == _grey()
    assert stripe._anim is None
    assert stripe._prev_color is None


def test_grey_to_muted_animates_forward(stripe, qapp):
    """Rank 0 -> Rank 1 = forward fill: _progress animates, 600 ms, InOutQuad."""
    stripe.set_color(_grey())
    stripe.set_color(_ttr_muted(qapp))
    assert stripe._anim is not None
    assert stripe._anim_kind == "forward"
    assert stripe._anim.duration() == 600
    assert stripe._anim.easingCurve().type() == QEasingCurve.InOutQuad
    assert stripe._prev_color == _grey()


def test_muted_to_full_animates_forward(stripe, qapp):
    """Rank 1 -> Rank 2 = forward fill."""
    stripe.set_color(_ttr_muted(qapp))
    stripe.set_color(_ttr_full())
    assert stripe._anim is not None
    assert stripe._anim_kind == "forward"


def test_full_to_muted_crossfades(stripe, qapp):
    """Rank 2 -> Rank 1 = backward cross-fade: _blend animates, 400 ms, InOutQuad."""
    stripe.set_color(_ttr_full())
    stripe.set_color(_ttr_muted(qapp))
    assert stripe._anim is not None
    assert stripe._anim_kind == "backward"
    assert stripe._anim.duration() == 400
    assert stripe._anim.easingCurve().type() == QEasingCurve.InOutQuad


def test_full_to_grey_crossfades(stripe):
    """Rank 2 -> Rank 0 = backward cross-fade."""
    stripe.set_color(_ttr_full())
    stripe.set_color(_grey())
    assert stripe._anim is not None
    assert stripe._anim_kind == "backward"


def test_same_color_short_circuits(stripe):
    """Calling set_color with the current color is a no-op (settled state)."""
    stripe.set_color(_ttr_full())
    _settle(stripe)
    stripe.set_color(_ttr_full())
    assert stripe._anim is None


def test_same_color_while_animating_does_not_cancel(stripe, qapp):
    """Calling set_color with the same destination while animating leaves
    the in-flight animation untouched (idempotent re-brand calls)."""
    stripe.set_color(_ttr_muted(qapp))
    stripe.set_color(_ttr_full())
    first_anim = stripe._anim
    # Second call with the identical target: must be a pure no-op.
    stripe.set_color(_ttr_full())
    assert stripe._anim is first_anim
    assert stripe._anim_kind == "forward"


def test_set_color_aborts_in_flight(stripe, qapp):
    """A second set_color cancels the first animation."""
    stripe.set_color(_grey())
    stripe.set_color(_ttr_muted(qapp))
    first_anim = stripe._anim
    stripe.set_color(_ttr_full())
    # The new animation is now in flight; the old one was stopped.
    assert stripe._anim is not None
    assert stripe._anim is not first_anim
    assert first_anim.state() == QPropertyAnimation.Stopped


def test_settles_at_target_forward(stripe, qapp):
    """After a forward animation completes, _color is the target,
    _prev_color is cleared, _progress is reset."""
    stripe.set_color(_grey())
    stripe.set_color(_ttr_muted(qapp))
    _settle(stripe)
    assert stripe._color == _ttr_muted(qapp)
    assert stripe._prev_color is None
    assert stripe._anim is None
    assert stripe._progress == 0.0


def test_settles_at_target_backward(stripe):
    """After a backward animation completes, _color is the target,
    _prev_color is cleared, _blend is reset."""
    stripe.set_color(_ttr_full())
    stripe.set_color(_grey())
    _settle(stripe)
    assert stripe._color == _grey()
    assert stripe._prev_color is None
    assert stripe._anim is None
    assert stripe._blend == 0.0


def test_muted_brand_helper_reduces_saturation():
    """_muted_brand returns a color with ~55% saturation, hue preserved."""
    from tabs.multitoon._compact_layout import _muted_brand
    full = QColor("#4A8FE7")
    muted = _muted_brand(full)
    # Hue preserved
    assert abs(muted.hslHue() - full.hslHue()) <= 1
    # Saturation reduced to ~55% of 255 = ~140
    assert 130 <= muted.hslSaturation() <= 150


def test_fixed_height_3px(stripe):
    """Stripe is fixed at 3 px tall."""
    assert stripe.height() == 3 or stripe.maximumHeight() == 3
