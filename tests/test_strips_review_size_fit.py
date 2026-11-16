"""Per-window preset fallback and restoration across width boundaries."""
import pytest
from PySide6.QtWidgets import QWidget
from tests.test_strips_controller import Keymaps, rig, settle
from utils import chord_capture_state
from utils.strips import layout as L
from utils.strips.model import StripModel


@pytest.mark.parametrize('previous,width,expected', [
    ('large', 436, 'large'), ('large', 435, 'medium'),
    ('medium', 439, 'medium'), ('medium', 440, 'large'),
    ('medium', 366, 'medium'), ('medium', 365, 'small'),
    ('small', 369, 'small'), ('small', 370, 'medium'),
    ('small', 200, 'small'), ('small', 800, 'large'),
])
def test_preset_thresholds_and_four_pixel_restoration_hysteresis(previous, width, expected):
    assert L.fitted_size(StripModel(home=True), 'neon', 'large', previous,
                         width, 1.0, 1.0) == expected


@pytest.mark.parametrize('maximum', ['small', 'medium'])
def test_restoration_never_exceeds_configured_preset(maximum):
    assert L.fitted_size(StripModel(home=True), 'neon', maximum, 'small',
                         1000, 1.0, 1.0) == maximum


def test_fit_accounts_for_true_size_compensation_and_device_ratio():
    model = StripModel(home=True)
    # At 80% Qt scale, a 436-native-px row plus margins occupies 545 logical px.
    assert L.fitted_size(model, 'neon', 'large', 'large', 545, 1.25, .8) == 'large'
    assert L.fitted_size(model, 'neon', 'large', 'large', 544, 1.25, .8) == 'medium'


def test_fallback_is_per_strip_closes_capture_first_and_rescales_counters(rig):
    _, controller, _ = rig(keymaps=Keymaps(), size='large')
    first = controller.follower.surface('101')
    second = controller.follower.surface('102')
    card = controller.open_editor('101', 1)
    settle()
    card.begin_capture('forward')
    observed = []
    first.scale_changing.connect(lambda: observed.append(
        (first.strip.scale(), chord_capture_state.is_active(), QWidget.keyboardGrabber())))
    first.place((100, 50, 360, 600))
    assert observed == [(1.5, False, None)]
    assert first.strip.scale() == 1.0
    assert second.strip.scale() == 1.5
    assert controller.popovers.open_tag('101') == ''
    counters = controller.popovers.counters_surface('101')
    assert counters.content._scale == first.strip.scale()
    assert first.strip.row_size().width() <= 360 - L.CLIENT_MARGIN
    first.place((100, 50, 800, 600))
    assert first.strip.scale() == 1.5


def test_repeated_samples_at_boundary_do_not_flap_or_repeat_logs(rig, capsys):
    _, controller, _ = rig(keymaps=Keymaps(), size='large')
    surface = controller.follower.surface('101')
    capsys.readouterr()
    for width in (435, 436, 439, 435, 439):
        surface.place((100, 50, width, 600))
        assert surface.strip.scale() == 1.25
    lines = [s for s in capsys.readouterr().out.splitlines() if 'size ' in s]
    assert len(lines) == 1
    surface.place((100, 50, 440, 600))
    assert surface.strip.scale() == 1.5
    assert 'medium -> large' in capsys.readouterr().out
