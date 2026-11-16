"""The Windows paths of the strips, with every Win32 call mocked.

Nothing here has run on Windows. These tests pin the maths and the unit
conversions (physical pixels from the system, logical pixels in Qt) so that
the first real run only has to find what reading could not.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ctypes

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from utils import ghost_cursors
from utils.overlay.backend import OverlayBackend
from utils.strips import attach
from utils.strips import layout as L
from utils.strips.attach import WS_EX_TRANSPARENT, Win32TopmostAttach, win32_occluders
from utils.strips.model import StripModel
from utils.strips.popovers import pointer_watch
from utils.strips.popovers.pointer_watch import PointerWatch, _PollProbe
from utils.strips.popovers.surface import PopoverSurface
from utils.strips.strip_surface import StripSurface

GAME, OTHER, OVERLAY, STRIP_WIN, MAIN = 10, 20, 30, 40, 50
SCALE = 1.5                      # Windows at 150%


@pytest.fixture
def win(monkeypatch):
    """A pretend desktop: z-order snapshot (top first), ex-styles and visible
    frames, all in PHYSICAL pixels, as Windows reports them."""
    state = {"snapshot": [], "styles": {}, "frames": {}}
    monkeypatch.setattr(ghost_cursors, "_win32_zorder_snapshot", lambda: state["snapshot"])
    monkeypatch.setattr(attach, "_win32_ex_style", lambda hwnd: state["styles"].get(hwnd, 0))
    monkeypatch.setattr(attach, "_win32_frame_bounds", lambda hwnd: state["frames"].get(hwnd))
    return state


def physical(rect: QRect) -> tuple:
    return (round(rect.left() * SCALE), round(rect.top() * SCALE),
            round((rect.left() + rect.width()) * SCALE),
            round((rect.top() + rect.height()) * SCALE))


class At150(Win32TopmostAttach):
    """The strategy on a 150% display: native / 1.5 = logical."""

    def to_logical(self, x, y):
        return round(x / SCALE), round(y / SCALE)

    def region_ratio(self, surface):
        return SCALE


GAME_L = QRect(100, 100, 800, 600)            # logical, on screen
STRIP_L = QRect(300, 106, 400, 66)            # the strip, top centre of the game
FULL = QRegion(QRect(0, 0, 400, 66))


# -- which windows count as covering the game ------------------------------------

def test_occluders_are_what_is_above_the_game_minus_ours_and_click_through(win):
    win["styles"] = {OVERLAY: WS_EX_TRANSPARENT | 0x80000}
    snapshot = [(OVERLAY, (0, 0, 2880, 1800), 9), (STRIP_WIN, (450, 159, 1050, 258), 1),
                (OTHER, (0, 0, 600, 600), 7), (GAME, physical(GAME_L), 5),
                (99, (0, 0, 3000, 3000), 6)]
    out = win32_occluders(snapshot, GAME, [STRIP_WIN])
    assert [hwnd for hwnd, _rect, _pid in out] == [OTHER, GAME]


def test_game_not_in_the_snapshot_means_no_answer(win):
    assert win32_occluders([(OTHER, (0, 0, 10, 10), 7)], GAME, []) is None


def test_visible_frame_replaces_the_window_rectangle(win):
    win["frames"] = {OTHER: (7, 0, 593, 593)}
    out = win32_occluders([(OTHER, (0, 0, 600, 600), 7), (GAME, physical(GAME_L), 5)],
                          GAME, [])
    assert out[0][1] == (7, 0, 593, 593)
    assert out[1][1] == physical(GAME_L)          # no frame known: the rectangle


# -- the gate, in logical pixels on a 150% display --------------------------------

def test_uncovered_strip_is_whole(win):
    win["snapshot"] = [(GAME, physical(GAME_L), 5)]
    assert At150().visible_region(STRIP_L, str(GAME), []) == FULL


def test_no_snapshot_fails_open_and_a_missing_game_shows_nothing(win):
    win["snapshot"] = None
    assert At150().visible_region(STRIP_L, str(GAME), []) is None
    win["snapshot"] = [(OTHER, (0, 0, 10, 10), 7)]       # minimized games are not listed
    assert At150().visible_region(STRIP_L, str(GAME), []).isEmpty()
    assert At150().visible_region(STRIP_L, "not-a-window", []) is None


def test_a_window_over_the_left_half_masks_exactly_that_half(win):
    cover = QRect(0, 0, 500, 400)                        # logical: ends at x = 500
    win["snapshot"] = [(OTHER, physical(cover), 7), (GAME, physical(GAME_L), 5)]
    region = At150().visible_region(STRIP_L, str(GAME), [])
    assert region == QRegion(QRect(200, 0, 200, 66))


def test_the_invisible_resize_border_does_not_eat_the_strip(win):
    """GetWindowRect reports 7 physical px of invisible border on each side.
    Masking by it would cut the strip short of the window's visible edge."""
    cover = QRect(0, 0, 500, 400)
    left, top, right, bottom = physical(cover)
    win["snapshot"] = [(OTHER, (left - 7, top, right + 7, bottom + 7), 7),
                       (GAME, physical(GAME_L), 5)]
    without = At150().visible_region(STRIP_L, str(GAME), [])
    assert without.boundingRect().left() == 205          # 7 px / 1.5 too far
    win["frames"] = {OTHER: (left, top, right, bottom)}
    assert At150().visible_region(STRIP_L, str(GAME), []) == QRegion(QRect(200, 0, 200, 66))


def test_a_click_through_overlay_above_everything_covers_nothing(win):
    """Another program's full-screen overlay, or our own ghost glove."""
    win["styles"] = {OVERLAY: WS_EX_TRANSPARENT}
    win["snapshot"] = [(OVERLAY, (0, 0, 2880, 1800), 9), (GAME, physical(GAME_L), 5)]
    assert At150().visible_region(STRIP_L, str(GAME), []) == FULL
    win["styles"] = {}
    assert At150().visible_region(STRIP_L, str(GAME), []).isEmpty()


def test_our_strips_never_cover_each_other_but_the_apps_window_does(win):
    win["snapshot"] = [(STRIP_WIN, physical(STRIP_L), 1), (GAME, physical(GAME_L), 5)]
    assert At150().visible_region(STRIP_L, str(GAME), [STRIP_WIN]) == FULL
    win["snapshot"] = [(MAIN, physical(QRect(0, 0, 500, 400)), 1),
                       (STRIP_WIN, physical(STRIP_L), 1), (GAME, physical(GAME_L), 5)]
    assert (At150().visible_region(STRIP_L, str(GAME), [STRIP_WIN])
            == QRegion(QRect(200, 0, 200, 66)))


def test_strip_is_clipped_to_the_game_but_a_popover_may_hang_past_it(win):
    win["snapshot"] = [(GAME, physical(GAME_L), 5)]
    low = QRect(300, 650, 266, 200)                      # 150 px past the game's bottom
    assert At150().visible_region(low, str(GAME), []) == QRegion(QRect(0, 0, 266, 50))
    assert (At150().visible_region(low, str(GAME), [], clip=False)
            == QRegion(QRect(0, 0, 266, 200)))


# -- units: physical from Windows, logical in Qt -------------------------------------

FLOSSBUD = StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit")


class Backend(OverlayBackend):
    def __init__(self):
        self.calls = []
        self.region = None

    def set_initial_state(self, window):
        self.calls.append("initial")

    def set_above(self, window):
        self.calls.append("above")

    def set_non_activating(self, window):
        self.calls.append("non_activating")

    def apply_input_region(self, window, region):
        self.region = QRegion(region)


def settle():
    for _ in range(4):
        QApplication.processEvents()


def test_strip_is_placed_in_logical_px_and_shaped_in_physical_px(qapp):
    backend = Backend()
    surface = StripSurface(At150(), backend, 1.0)
    surface.set_game_window(str(GAME))
    surface.set_model(FLOSSBUD)
    surface.place(physical(GAME_L)[:2] + (1200, 900))    # client rect as Windows gives it
    settle()
    assert surface.client_logical() == GAME_L
    row = surface.strip.row_size()
    geo = surface.geometry()
    assert abs(geo.x() + 14 + row.width() / 2 - 500) <= 1          # centred, logical
    assert geo.y() + 14 == 100 + 10                                # 10 logical px inside
    # The arbiter compares physical cursor positions: the region must be physical.
    block = surface.strip.block_rect(L.ENABLE).toAlignedRect()
    centre = QPoint(round(block.center().x() * SCALE), round(block.center().y() * SCALE))
    assert backend.region.contains(centre)
    assert backend.region.boundingRect().right() > surface.width()
    assert backend.calls == ["initial", "above", "non_activating"]
    surface.hide()
    surface.deleteLater()


def test_a_half_masked_strip_takes_no_clicks_in_the_masked_half(qapp):
    backend = Backend()
    surface = StripSurface(At150(), backend, 1.0)
    surface.set_game_window(str(GAME))
    surface.set_model(FLOSSBUD)
    surface.place(physical(GAME_L)[:2] + (1200, 900))
    settle()
    half = surface.width() // 2
    surface.set_visible_region(QRegion(QRect(half, 0, surface.width() - half, surface.height())))
    assert backend.region.boundingRect().left() >= round(half * SCALE) - 1
    portrait = surface.strip.block_rect(L.PORTRAIT).center()
    assert not backend.region.contains(
        QPoint(round(portrait.x() * SCALE), round(portrait.y() * SCALE)))
    surface.hide()
    surface.deleteLater()


def test_popovers_get_the_same_window_treatment(qapp):
    from utils.strips.popovers.menu import MenuItem, PillMenu
    backend = Backend()
    popover = PopoverSurface(At150(), backend, PillMenu([MenuItem("a", "Edit keyset")], "#E05252"))
    popover.present(QPoint(100, 100), STRIP_WIN)
    settle()
    assert backend.calls == ["initial", "above", "non_activating"]
    assert popover.is_presented()
    popover.dismiss()


# -- Escape and click-elsewhere by polling -------------------------------------------

class User32:
    def __init__(self):
        self.down = set()

    def GetAsyncKeyState(self, vk):
        return -32768 if vk in self.down else 0      # a SHORT with the top bit set


@pytest.fixture
def user32(monkeypatch):
    fake = User32()
    monkeypatch.setattr(pointer_watch.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": fake})(), raising=False)
    return fake


def test_any_mouse_button_counts_as_down(user32):
    probe = _PollProbe()
    assert probe.buttons_down() is False
    for vk in (0x01, 0x02, 0x04):                    # left, right, middle
        user32.down = {vk}
        assert probe.buttons_down() is True
    user32.down = {0x41}                              # a key is not a button
    assert probe.buttons_down() is False


def test_escape_is_reported_once_per_press(user32):
    probe = _PollProbe()
    assert probe.escape_pressed() is False
    user32.down = {0x1B}
    assert probe.escape_pressed() is True
    assert probe.escape_pressed() is False            # still held: not again
    user32.down = set()
    assert probe.escape_pressed() is False
    user32.down = {0x1B}
    assert probe.escape_pressed() is True


def test_escape_held_before_the_menu_opened_does_not_close_it(user32):
    probe = _PollProbe()
    user32.down = {0x1B}                              # held from before
    probe.grab_escape(True)                           # a popover opens now
    assert probe.escape_pressed() is False            # not a press meant for it
    user32.down = set()
    assert probe.escape_pressed() is False
    user32.down = {0x1B}
    assert probe.escape_pressed() is True             # the next real press is


def test_watch_on_windows_closes_on_a_press_elsewhere_and_on_escape(qapp, user32):
    cursor = {"pos": QPoint(500, 500)}
    watch = PointerWatch(_PollProbe(), lambda: cursor["pos"])
    events = []
    watch.pressed_outside.connect(lambda: events.append("outside"))
    watch.escape.connect(lambda: events.append("escape"))
    inside = QRect(100, 100, 50, 50)
    watch.watch(inside.contains)
    user32.down = {0x01}
    watch.tick()
    assert events == ["outside"]
    user32.down = set()
    watch.tick()
    cursor["pos"] = QPoint(120, 120)
    user32.down = {0x01}
    watch.tick()
    assert events == ["outside"]                      # a press on the popover itself
    user32.down = {0x1B}
    watch.tick()
    assert events == ["outside", "escape"]
    watch.shutdown()
