"""Strip geometry: block order, natural width, omitted blocks, collapse."""
import pytest

from utils.strips import layout as L
from utils.strips import tokens
from utils.strips.model import StripModel

NEON, FLAT = tokens.NEON_STYLE, tokens.FLAT_STYLE


def short(_text):
    return 10.0     # narrower than the plate's minimum width


def kinds(lay):
    return [b.kind for b in lay.blocks]


def test_block_order():
    lay = L.layout_strip(StripModel(home=True), NEON, short)
    assert kinds(lay) == [
        L.HOME, L.PORTRAIT, L.NAME, L.KEEP_ALIVE, L.CLICK_SYNC, L.SEPARATOR,
        L.KEYSET, L.KEYSET, L.KEYSET, L.ADD, L.SEPARATOR, L.ENABLE]
    xs = [b.rect.x() for b in lay.blocks if b.kind != L.NAME]
    assert xs == sorted(xs)


def test_natural_width_matches_the_handoff():
    """Neon, three keysets plus add: about 373 px; the home block adds its
    circle, its 3 px margin and one gap."""
    lay = L.layout_strip(StripModel(), NEON, short)
    assert lay.width == pytest.approx(373.0)
    assert lay.height == 38
    home = L.layout_strip(StripModel(home=True), NEON, short)
    assert home.width - lay.width == pytest.approx(28 + 3 + 6)


def test_flat_is_tighter():
    lay = L.layout_strip(StripModel(), FLAT, short)
    # 36 + (86 - 11) + 5 + (26+5+26) + 5 + 2 + 5 + (4*26 + 3*5) + 5 + 2 + 5 + 26
    assert lay.width == pytest.approx(342.0)
    assert lay.height == 36


def test_everything_is_vertically_centred():
    lay = L.layout_strip(StripModel(home=True), NEON, short)
    for b in lay.blocks:
        assert b.rect.center().y() == pytest.approx(19.0)


def test_name_plate_tucks_under_the_portrait_and_grows_with_the_name():
    lay = L.layout_strip(StripModel(), NEON, short)
    portrait, plate = lay.find(L.PORTRAIT), lay.find(L.NAME)
    assert plate.rect.x() == portrait.rect.right() - 13
    assert plate.rect.width() == 90
    wide = L.layout_strip(StripModel(), NEON, lambda _t: 150.0)
    # border 2 + padding 18 + text + padding 10 + border 2
    assert wide.find(L.NAME).rect.width() == 182
    flat = L.layout_strip(StripModel(), FLAT, lambda _t: 150.0)
    assert flat.find(L.NAME).rect.width() == 177     # 17 + text + 10, no border


def test_a_feature_that_is_off_app_wide_omits_its_block():
    lay = L.layout_strip(StripModel(click_sync=None), NEON, short)
    assert L.CLICK_SYNC not in kinds(lay)
    assert L.KEEP_ALIVE in kinds(lay)
    full = L.layout_strip(StripModel(), NEON, short)
    assert full.width - lay.width == pytest.approx(28 + 6)


def test_no_tools_means_no_first_separator():
    lay = L.layout_strip(StripModel(keep_alive=None, click_sync=None), NEON, short)
    assert kinds(lay).count(L.SEPARATOR) == 1
    assert kinds(lay)[:3] == [L.PORTRAIT, L.NAME, L.KEYSET]


def test_add_is_gone_at_the_maximum():
    m = StripModel(keysets=tuple(range(1, 9)), active=5, show_add=False)
    lay = L.layout_strip(m, NEON, short)
    assert [b.number for b in lay.blocks if b.kind == L.KEYSET] == list(range(1, 9))
    assert L.ADD not in kinds(lay)


def test_hidden_sets_keep_their_numbers():
    lay = L.layout_strip(StripModel(keysets=(1, 4, 7), active=4), NEON, short)
    assert [b.number for b in lay.blocks if b.kind == L.KEYSET] == [1, 4, 7]


def test_fits_in_full_when_there_is_room():
    lay = L.fit_strip(StripModel(), NEON, short, 373 + 24)
    assert lay.collapse == L.FULL
    assert L.fit_strip(StripModel(), NEON, short, None).collapse == L.FULL


def test_narrow_window_drops_the_name_first():
    lay = L.fit_strip(StripModel(), NEON, short, 373 + 23)
    assert lay.collapse == L.NO_NAME
    assert L.NAME not in kinds(lay)
    assert lay.width == pytest.approx(373 - 77)
    assert lay.identity_rect() == lay.find(L.PORTRAIT).rect


def test_narrower_still_keeps_only_the_active_keyset_and_the_add():
    m = StripModel(keysets=(1, 2, 3), active=2)
    lay = L.fit_strip(m, NEON, short, 260)
    assert lay.collapse == L.ACTIVE_SET_ONLY
    assert [b.number for b in lay.blocks if b.kind == L.KEYSET] == [2]
    assert L.ADD in kinds(lay)
    assert lay.width == pytest.approx(228.0) and lay.width <= 260 - 24


def test_hit_testing():
    lay = L.layout_strip(StripModel(), NEON, short)
    two = lay.find(L.KEYSET, 2)
    c = two.rect.center()
    assert lay.hit(c.x(), c.y()).key == (L.KEYSET, 2)
    sep = lay.find(L.SEPARATOR)
    assert lay.hit(sep.rect.center().x(), sep.rect.center().y()) is None
    # In the gap between two blocks: nothing.
    assert lay.hit(two.rect.right() + 3, c.y()) is None
    # Where the plate is tucked under the portrait, the portrait wins.
    plate = lay.find(L.NAME)
    assert lay.hit(plate.rect.x() + 4, 19).kind == L.PORTRAIT
    assert lay.hit(plate.rect.right() - 4, 19).kind == L.NAME


def test_dimmed_follows_enabled_and_running():
    assert not StripModel().dimmed
    assert StripModel(enabled=False).dimmed
    assert StripModel(running=False).dimmed
