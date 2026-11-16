"""The strip surface: where it lands, when it shows, where it takes input."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from utils import ui_scale
from utils.overlay.backend import OverlayBackend
from utils.strips import layout as L
from utils.strips.attach import AttachStrategy
from utils.strips.follow import StripFollower
from utils.strips.model import StripModel
from utils.strips.strip_surface import (ANCHOR_INSET, StripSurface,
                                        strip_origin, strip_scale)
from utils.strips.strip_widget import MARGIN

FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")
CLIENT = (100, 50, 800, 600)


class Backend(OverlayBackend):
    def __init__(self):
        self.regions = []

    def apply_input_region(self, window, region):
        self.regions.append(QRegion(region))

    @property
    def last(self):
        return self.regions[-1]


class Strategy(AttachStrategy):
    """Records attaches; native units are logical so tests read plainly."""
    name = "test"
    logical_native = True

    def __init__(self, ok=True, ratio=1.0):
        self.ok, self.ratio = ok, ratio
        self.attached = []
        self.prepared = 0

    def prepare(self, surface, backend):
        self.prepared += 1

    def attach(self, surface, backend, game_wid):
        self.attached.append(game_wid)
        return self.ok

    def region_ratio(self, surface):
        return self.ratio


@pytest.fixture
def make(qapp):
    made = []

    def _make(strategy=None, model=FLOSSBUD, scale=1.0):
        strategy = strategy or Strategy()
        backend = Backend()
        surface = StripSurface(strategy, backend, scale)
        surface.set_game_window("4242")
        surface.set_model(model)
        made.append(surface)
        return surface, strategy, backend

    yield _make
    for s in made:
        s.hide()
        s.deleteLater()


def settle():
    for _ in range(4):
        QApplication.processEvents()


def test_strip_scale_is_the_inverse_of_the_ui_scale():
    assert strip_scale({}) == 1.0
    assert strip_scale({ui_scale.ENV_ACTIVE: "0.8"}) == pytest.approx(1.25)
    assert strip_scale({ui_scale.ENV_ACTIVE: "junk"}) == 1.0
    assert strip_scale({ui_scale.ENV_ACTIVE: "9"}) == 1.0


def test_origin_centres_the_row_and_insets_it():
    origin = strip_origin(QRect(100, 50, 800, 600), QSize(380, 38),
                          QPoint(14, 14), 1.0)
    assert origin == QPoint(100 + (800 - 380) // 2 - 14, 50 + 10 - 14)
    # At scale 1.25 the inset and the halo margin grow together.
    origin = strip_origin(QRect(0, 0, 1000, 600), QSize(500, 48),
                          QPoint(18, 18), 1.25)
    assert origin == QPoint(250 - 18, round(12.5 - 18))


def test_place_centres_the_row_on_the_client_area(make):
    surface, _strategy, _backend = make()
    surface.place(CLIENT)
    settle()
    row = surface.strip.row_size()
    geo = surface.geometry()
    row_left = geo.x() + MARGIN
    assert abs((row_left + row.width() / 2) - (100 + 400)) <= 1
    assert geo.y() + MARGIN == 50 + ANCHOR_INSET
    assert geo.size() == surface.strip.size()


def test_first_show_is_staged_until_the_tie_is_in_place(make):
    surface, strategy, backend = make()
    assert not surface.isVisible()
    surface.place(CLIENT)
    # Mapped, but nothing presented before the first paint and the attach.
    assert surface.isVisible() and not surface.is_presented()
    assert strategy.attached == []
    settle()
    assert strategy.prepared == 1
    assert strategy.attached == ["4242"]
    assert surface.is_presented()


def test_input_region_is_exactly_the_blocks(make):
    surface, _s, backend = make()
    surface.place(CLIENT)
    settle()
    region = backend.last
    rects = surface.strip.input_rects()
    expected = QRegion()
    for r in rects:
        expected = expected.united(QRegion(r))
    assert region == expected
    sep = surface.strip.block_rect(L.SEPARATOR).center().toPoint()
    assert not region.contains(sep)
    assert not region.contains(QPoint(2, 2))
    assert region.contains(surface.strip.block_rect(L.ENABLE).center().toPoint())


def test_input_region_is_in_device_pixels(make):
    surface, _s, backend = make(Strategy(ratio=2.0))
    surface.place(CLIENT)
    settle()
    r = surface.strip.block_rect(L.ENABLE).toAlignedRect()
    centre = QPoint(r.center().x() * 2, r.center().y() * 2)
    assert backend.last.contains(centre)
    assert backend.last.boundingRect().right() > surface.width()


def test_conceal_takes_no_input_and_stays_mapped(make):
    surface, strategy, backend = make()
    surface.place(CLIENT)
    settle()
    surface.conceal()
    assert backend.last.isEmpty()
    assert not surface.is_presented()
    assert surface.isVisible()                       # never unmapped
    surface.place((140, 50, 800, 600))
    settle()
    assert surface.is_presented()
    assert not backend.last.isEmpty()
    assert strategy.attached == ["4242"]             # still the same map


def test_a_failed_attach_keeps_the_strip_hidden(make, capsys):
    surface, _s, backend = make(Strategy(ok=False))
    surface.place(CLIENT)
    settle()
    assert not surface.is_presented()
    assert all(r.isEmpty() for r in backend.regions)
    assert "attach failed" in capsys.readouterr().out


def test_our_own_unmap_drops_the_tie(make):
    surface, strategy, _b = make()
    surface.place(CLIENT)
    settle()
    surface.hide()
    surface.place(CLIENT)
    settle()
    assert strategy.attached == ["4242", "4242"]
    assert surface.is_presented()


def test_gate_fully_covered_shows_nothing(make):
    surface, _s, backend = make()
    surface.place(CLIENT)
    settle()
    surface.set_visible_region(QRegion())
    assert not surface.is_presented() and backend.last.isEmpty()
    surface.set_visible_region(None)
    assert surface.is_presented() and not backend.last.isEmpty()


def test_gate_partial_cover_masks_paint_and_input(make):
    surface, _s, backend = make()
    surface.place(CLIENT)
    settle()
    half = surface.width() // 2
    surface.set_visible_region(QRegion(QRect(half, 0, surface.width() - half,
                                             surface.height())))
    assert surface.is_presented()
    assert surface.mask() == QRegion(QRect(half, 0, surface.width() - half,
                                           surface.height()))
    assert backend.last.boundingRect().left() >= half
    assert backend.last.contains(surface.strip.block_rect(L.ENABLE).center().toPoint())
    # A full-rect region is no mask at all.
    surface.set_visible_region(QRegion(surface.rect()))
    assert surface.mask().isEmpty()


def test_a_wider_strip_stays_centred(make):
    surface, _s, _b = make()
    surface.place(CLIENT)
    settle()
    before = surface.width()
    surface.set_model(FLOSSBUD.with_(name="Captain Fluffy McSparkle"))
    assert surface.width() > before
    centre = surface.geometry().x() + surface.width() / 2
    assert abs(centre - 500) <= 1


def test_narrow_client_collapses_the_name(make):
    surface, _s, _b = make()
    surface.place((100, 50, 340, 600))
    settle()
    assert surface.strip.strip_layout().collapse == L.NO_NAME
    assert surface.strip.row_size().width() <= 340 - 24


def test_scale_makes_the_strip_true_size(make):
    surface, _s, _b = make(scale=1.25)
    surface.place(CLIENT)
    settle()
    assert surface.strip.block_rect(L.ENABLE).width() == pytest.approx(35.0)
    # The row's top edge is the scaled inset inside the client area, to the
    # pixel the surface can be placed on.
    row_top = surface.geometry().y() + surface.strip.row_offset().y()
    assert abs(row_top - (50 + 10 * 1.25)) <= 0.5
    # 800 logical px of client is 640 design px: still room for the name.
    assert surface.strip.strip_layout().collapse == L.FULL


def test_window_never_takes_focus(make):
    surface, _s, _b = make()
    assert surface.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert surface.testAttribute(Qt.WA_ShowWithoutActivating)
    assert surface.testAttribute(Qt.WA_TranslucentBackground)
    assert surface.focusPolicy() == Qt.NoFocus


def test_follower_places_hides_and_removes(qapp, capsys):
    rects = {"7": CLIENT}
    strategy = Strategy()
    follower = StripFollower(strategy, Backend(), geometry_fn=rects.get, scale=1.0)
    surface = follower.add("7")
    surface.set_model(FLOSSBUD)
    assert follower.add("7") is surface              # one strip per window
    follower.tracker.sample_now()
    assert not surface.isVisible()                   # one sample is not rest
    follower.tracker.sample_now()
    settle()
    assert surface.is_presented()
    rects["7"] = (160, 50, 800, 600)
    follower.tracker.sample_now()
    assert not surface.is_presented()                # hidden the moment it moves
    follower.tracker.sample_now()
    settle()
    assert surface.is_presented()
    assert abs(surface.geometry().x() + surface.width() / 2 - 560) <= 1
    del rects["7"]
    follower.tracker.sample_now()
    assert not surface.is_presented()
    follower.remove("7")
    assert follower.surface("7") is None and follower.tracker.windows() == ()
    follower.shutdown()


def test_stamp_names_the_strategy_and_look_once(qapp, capsys, monkeypatch):
    from utils.strips import follow
    monkeypatch.setattr(follow, "_stamped", False)
    a = StripFollower(Strategy(), Backend(), geometry_fn=lambda w: None, style="flat")
    a.start()
    b = StripFollower(Strategy(), Backend(), geometry_fn=lambda w: None)
    b.start()
    a.shutdown(), b.shutdown()
    out = capsys.readouterr().out
    assert out.count("[Strips] ") == 1
    assert "[Strips] attach=test style=flat size=small" in out
