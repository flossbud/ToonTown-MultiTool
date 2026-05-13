"""Pins H_FULL. Restored to 800 (the pre-chip-rail value) so the Full-UI
trigger threshold stays at 1280×860 — users who used to enter Full at that
size still can. The earlier 852/864 bumps preserved cards-at-100% at the
trigger but pushed the threshold past habitual window heights. At the
restored 860 trigger height, the 2×2 card grid renders at ~99.5% of its
632×360 reference (4 px of compression on a 744 px design budget) — a
negligible visual concession for an accessible threshold."""

from main import H_FULL, W_FULL


def test_h_full_is_800_for_accessible_full_threshold():
    assert H_FULL == 800


def test_w_full_unchanged_at_1280():
    assert W_FULL == 1280
