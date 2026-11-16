"""X11 with no compositing manager: strips are shaped windows, not
translucent ones (which would show as black rectangles)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from utils.overlay.backend import OverlayBackend
from utils.strips import layout as L
from utils.strips import x11_shape
from utils.strips.attach import AttachStrategy, X11TransientAttach
from utils.strips.follow import StripFollower
from utils.strips.model import StripModel
from utils.strips.popovers.counters import CountersModel, CountersView
from utils.strips.popovers.home import HomePanel
from utils.strips.popovers.menu import MenuItem, PillMenu
from utils.strips.popovers.surface import PopoverSurface
from utils.strips.strip_surface import StripSurface
from utils.strips.strip_widget import StripWidget

FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")
CLIENT = (100, 50, 800, 600)


class Shaped(AttachStrategy):
    """A strategy that can switch between translucent and shaped."""
    name = "test"
    logical_native = True

    def __init__(self, shaped=True):
        self.is_shaped = shaped
        self.next = shaped
        self.shapes = []          # every region handed to set_shape, in order

    def shaped(self):
        return self.is_shaped

    def refresh(self):
        changed, self.is_shaped = self.next != self.is_shaped, self.next
        return changed

    def set_shape(self, surface, region):
        self.shapes.append(None if region is None else QRegion(region))


def settle():
    for _ in range(4):
        QApplication.processEvents()


# -- detection -------------------------------------------------------------------

def test_strategy_is_shaped_exactly_when_no_compositor_owns_the_selection(monkeypatch):
    monkeypatch.setattr(x11_shape, "composited", lambda: False)
    strategy = X11TransientAttach()
    assert strategy.shaped()
    monkeypatch.setattr(x11_shape, "composited", lambda: True)
    assert strategy.refresh() is True and not strategy.shaped()
    assert strategy.refresh() is False                  # no change, no work


def test_an_unreachable_display_counts_as_composited(monkeypatch):
    """Never fall back to shaped windows on a guess."""
    def boom():
        raise OSError("no display")
    monkeypatch.setattr(x11_shape, "_get_display", boom)
    assert x11_shape.composited() is True


def test_shape_is_sent_in_device_pixels(monkeypatch):
    sent = []
    monkeypatch.setattr(x11_shape, "composited", lambda: False)
    monkeypatch.setattr(x11_shape, "set_bounding", lambda wid, rects: sent.append((wid, rects)))
    monkeypatch.setattr(x11_shape, "clear_bounding", lambda wid: sent.append((wid, None)))

    class Surface:
        def winId(self):
            return 77

        def devicePixelRatioF(self):
            return 2.0

    strategy = X11TransientAttach()
    strategy.set_shape(Surface(), QRegion(QRect(10, 5, 28, 28)))
    assert sent == [(77, [(20, 10, 56, 56)])]
    strategy.set_shape(Surface(), QRegion())
    assert sent[-1] == (77, [])                          # nothing on screen
    strategy.set_shape(Surface(), None)
    assert sent[-1] == (77, None)                        # the whole window back


def test_other_platforms_are_never_shaped():
    assert not AttachStrategy().shaped() and AttachStrategy().refresh() is False


# -- what is solid ------------------------------------------------------------------

def test_strip_shape_is_the_blocks_and_not_the_gaps_or_the_halo(qapp):
    strip = StripWidget()
    strip.set_model(FLOSSBUD.with_(home=True))
    region = strip.shape_region()
    for b in strip.strip_layout().blocks:
        centre = strip.block_rect(b.kind, b.number).center().toPoint()
        assert region.contains(centre), b.kind
    two, three = strip.block_rect(L.KEYSET, 2), strip.block_rect(L.KEYSET, 3)
    gap = QPoint(int((two.right() + three.left()) / 2), int(two.center().y()))
    assert not region.contains(gap)
    assert not region.contains(QPoint(2, 2))
    # Round blocks stay round: the corner of the portrait's box is not solid.
    portrait = strip.block_rect(L.PORTRAIT)
    assert not region.contains(portrait.topLeft().toPoint() + QPoint(1, 1))
    assert strip.rect().contains(region.boundingRect())


def test_popover_shapes(qapp):
    counters = CountersView()
    counters.set_style("flat")
    counters.set_model(CountersModel(beans=456, bank=12840))
    shape = counters.shape_region()
    assert shape.contains(counters.lock_rect().center().toPoint())
    assert not shape.contains(QPoint(1, 1))
    menu = PillMenu([MenuItem("a", "Edit keyset"), MenuItem("b", "Hide keyset")], "#E05252")
    shape = menu.shape_region()
    assert shape.contains(menu.pill_rect(1).center().toPoint())
    between = QPoint(int(menu.pill_rect(0).center().x()),
                     int((menu.pill_rect(0).bottom() + menu.pill_rect(1).top()) / 2))
    assert not shape.contains(between)
    assert shape.contains(QPoint(menu.width() // 2, 4))          # the caret
    panel = HomePanel("neon")
    shape = panel.shape_region()
    card = panel.card_rect()
    assert shape.contains(card.center().toPoint())
    assert not shape.contains(QPoint(int(card.left() - 6), int(card.center().y())))   # halo


# -- surfaces ---------------------------------------------------------------------------

@pytest.fixture
def strip_surface(qapp):
    made = []

    def _make(strategy):
        surface = StripSurface(strategy, OverlayBackend(), 1.0)
        surface.set_game_window("4242")
        surface.set_model(FLOSSBUD)
        made.append(surface)
        return surface

    yield _make
    for s in made:
        s.hide()
        s.deleteLater()


def test_shaped_strip_is_cut_to_nothing_until_it_is_tied_then_to_its_blocks(strip_surface):
    strategy = Shaped()
    surface = strip_surface(strategy)
    surface.place(CLIENT)
    # Mapped but staged: the first shape is empty, before the window shows.
    assert strategy.shapes and strategy.shapes[0].isEmpty()
    settle()
    assert surface.is_presented()
    assert strategy.shapes[-1] == surface.strip.shape_region()
    assert not strategy.shapes[-1].isEmpty()


def test_shaped_strip_hides_by_shape_while_its_window_moves(strip_surface):
    strategy = Shaped()
    surface = strip_surface(strategy)
    surface.place(CLIENT)
    settle()
    surface.conceal()
    assert strategy.shapes[-1].isEmpty()            # opacity alone would do nothing
    surface.place((140, 50, 800, 600))
    settle()
    assert not strategy.shapes[-1].isEmpty()


def test_shape_follows_the_strip_when_it_changes(strip_surface):
    strategy = Shaped()
    surface = strip_surface(strategy)
    surface.place(CLIENT)
    settle()
    before = strategy.shapes[-1]
    surface.set_model(FLOSSBUD.with_(keysets=(1, 2)))
    assert strategy.shapes[-1] != before
    assert strategy.shapes[-1] == surface.strip.shape_region()


def test_translucent_strip_never_touches_the_shape(strip_surface):
    strategy = Shaped(shaped=False)
    surface = strip_surface(strategy)
    surface.place(CLIENT)
    settle()
    surface.conceal()
    assert strategy.shapes == []


def test_compositor_appearing_gives_the_whole_window_back(qapp, capsys):
    strategy = Shaped()
    rects = {"7": CLIENT}
    follower = StripFollower(strategy, OverlayBackend(), geometry_fn=rects.get, scale=1.0)
    surface = follower.add("7")
    surface.set_model(FLOSSBUD)
    follower.tracker.sample_now(), follower.tracker.sample_now()
    settle()
    assert not strategy.shapes[-1].isEmpty()
    follower.check_desktop()                         # nothing changed: nothing done
    count = len(strategy.shapes)
    strategy.next = False                            # a compositor started
    follower.check_desktop()
    assert strategy.shapes[count] is None            # shape cleared
    assert "compositing manager found" in capsys.readouterr().out
    strategy.next = True                             # and stopped again
    follower.check_desktop()
    assert strategy.shapes[-1] == surface.strip.shape_region()
    assert "compositing manager gone" in capsys.readouterr().out
    follower.shutdown()


def test_shaped_popover_and_flat_counters_get_a_backing(qapp):
    strategy = Shaped()
    view = CountersView()
    view.set_style("flat")
    view.set_model(CountersModel(beans=1, bank=2))
    popover = PopoverSurface(strategy, OverlayBackend(), view)
    popover.present(QPoint(50, 50), None)
    assert strategy.shapes[0].isEmpty()
    settle()
    assert strategy.shapes[-1] == view.shape_region()
    assert view._backed is True                      # bare text needs a body to be a shape
    popover.conceal()
    assert strategy.shapes[-1].isEmpty()
    strategy.next = False
    strategy.refresh()
    popover.refresh_presentation()
    assert strategy.shapes[-1] is None and view._backed is False
    popover.dismiss()
