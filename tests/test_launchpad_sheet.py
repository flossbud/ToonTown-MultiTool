"""Launchpad sheet host and material, mounted in a parent under the app's
real stylesheet in both themes."""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget

from utils import theme_manager
from utils.widgets.launchpad import material as m
from utils.widgets.launchpad.slide_sheet import (
    HEADER_H, SHEET_HEAD_H, SHEET_W, SLIDE_MS, SlideSheetHost,
)

BACKDROP = QColor("#c0803a")


@contextmanager
def _theme(qapp, theme):
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    try:
        theme_manager.apply_theme(qapp, theme)
        yield
    finally:
        qapp.setStyleSheet(before_sheet)
        qapp.setPalette(before_palette)
        theme_manager._APPLIED_THEME = before_marker


@pytest.fixture(params=["dark", "light"])
def themed(qapp, request):
    with _theme(qapp, request.param):
        yield request.param == "dark"


@pytest.fixture
def reduced(monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)


class _Window(QWidget):
    """880 x 860 stand-in with a solid backdrop colour under the header."""

    def __init__(self):
        super().__init__()
        self.resize(880, 860)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), BACKDROP)
        p.end()


def _content(is_dark):
    page = QWidget()
    lay = m.sheet_stack(page)
    card = m.GroupCard("#DAA520", "Card", is_dark=is_dark)
    row = m.SheetRow("Row", "desc", is_dark=is_dark)
    row.set_control(m.SheetToggle(True, "#DAA520", is_dark=is_dark))
    card.add_row(row)
    lay.addWidget(card)
    lay.addWidget(m.footer_label("footer", is_dark))
    return page, card, row


def _near(a: QColor, b: QColor, tol=6):
    return (abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol
            and abs(a.blue() - b.blue()) <= tol)


def _open(is_dark, **kw):
    win = _Window()
    host = SlideSheetHost(win, is_dark=is_dark)
    page, card, row = _content(is_dark)
    host.open(page, "#DAA520", "Keysets", "sub line", **kw)
    return win, host, page, card, row


# ── geometry and paint, mounted, both themes ───────────────────────────────

def test_geometry_mounted(qapp, themed, reduced):
    win, host, page, card, _ = _open(themed)
    assert host.geometry().top() == HEADER_H
    assert host.height() == 860 - HEADER_H
    assert host.panel.width() == SHEET_W
    assert host.panel.x() + SHEET_W == 880
    assert host.panel.header.height() == SHEET_HEAD_H
    win.show()
    win.resize(1000, 900)
    qapp.processEvents()
    assert host.width() == 1000 and host.height() == 900 - HEADER_H
    assert host.panel.x() + SHEET_W == 1000
    win.close()


def test_paint_mounted(qapp, themed, reduced):
    win, host, page, card, _ = _open(themed)
    qapp.processEvents()
    img = win.grab().toImage()
    pal = m.sheet_palette(themed)
    px = lambda x, y: img.pixelColor(x, y)
    # Header area above the host is untouched.
    assert _near(px(10, 10), BACKDROP, 0)
    # Scrim: the backdrop shows through, dimmed.
    s = px(40, 600)
    assert s.red() < BACKDROP.red() - 20
    # Identity top line, 2 px, across the panel.
    panel_x = 880 - SHEET_W
    assert _near(px(panel_x + 300, HEADER_H), QColor("#DAA520"))
    assert _near(px(panel_x + 300, HEADER_H + 1), QColor("#DAA520"))
    # Header fill is bg-deep; the body below the content is bg-app (a
    # stylesheet background leaking into the scroll area would change it).
    assert _near(px(panel_x + 300, HEADER_H + 2 + 20), m.qcolor(pal["bg_deep"]))
    assert _near(px(panel_x + 300, 840), m.qcolor(pal["bg_app"]))
    # Left border.
    assert _near(px(panel_x, 700), m.qcolor(pal["border_card"]))


def test_card_edges_land_on_the_handoff_padding(qapp, themed, reduced):
    win, host, page, card, _ = _open(themed)
    qapp.processEvents()
    top_left = card.mapTo(host.panel, QPoint(m.GLOW_PAD, m.GLOW_PAD))
    assert top_left.x() == 1 + 16          # left border + body padding
    assert top_left.y() == 2 + SHEET_HEAD_H + 14


def test_group_card_paints_its_tint_and_no_stylesheet_block(qapp, themed, reduced):
    win, host, page, card, row = _open(themed)
    qapp.processEvents()
    img = card.grab().toImage()
    top, bottom, border, _ = card._colors()
    inside = img.pixelColor(card.width() // 2, m.GLOW_PAD + 3)
    assert _near(inside, top, 10)
    # Rows draw their own translucent fill over the card's gradient, never an
    # opaque app background.
    rimg = row.grab().toImage()
    mid = rimg.pixelColor(rimg.width() // 2, 3)
    assert not _near(mid, QColor(theme_manager.get_theme_colors(themed)["bg_app"]), 1)


def test_labels_sized_by_their_own_stylesheet(qapp, themed, reduced):
    """The app's QWidget { font-size: 12pt } must not win over the sheet's
    sizes (title 15 px, row title 12.5 px)."""
    win, host, page, card, row = _open(themed)
    qapp.processEvents()
    assert host.panel.header.title_label.fontInfo().pixelSize() == 15
    assert card.title_label.fontInfo().pixelSize() == 15
    assert row.label_widget.fontInfo().pixelSize() in (12, 13)
    assert row.minimumHeight() >= m.ROW_MIN_H


# ── behaviour ───────────────────────────────────────────────────────────────

def test_open_close_signals_and_state(qapp, reduced):
    win, host, *_ = _open(True)
    seen = []
    host.closed.connect(lambda: seen.append("closed"))
    host.opened.connect(lambda: seen.append("opened"))
    assert host.is_open() and host.isVisibleTo(win)
    assert host.close() is True
    assert seen == ["closed"]
    assert not host.is_open() and not host.isVisibleTo(win)
    assert host.close() is False
    page = QWidget()
    host.open(page, "#3da343", "Settings")
    assert seen == ["closed", "opened"]
    assert host.current_content() is page


def test_swap_keeps_sheet_open_and_old_content_alive(qapp, reduced):
    win, host, first, *_ = _open(True)
    opened, changed = [], []
    host.opened.connect(lambda: opened.append(1))
    host.content_changed.connect(changed.append)
    second = QLabel("second")
    host.open(second, "#0077ff", "Accounts", "3 accounts")
    assert host.is_open()
    assert opened == []                     # a swap is not an open
    assert changed == [second]
    assert host.current_content() is second
    assert not first.isVisibleTo(host)
    assert first.parent() is host           # kept alive for its owner
    assert host.panel.header.title_label.fullText() == "Accounts"
    assert host.panel._identity == QColor("#0077ff")


def test_header_and_back(qapp, reduced):
    win, host, *_ = _open(True)
    hdr = host.panel.header
    assert not hdr.back_button.isVisibleTo(host)
    calls = []
    host.set_back(lambda: calls.append(1))
    assert hdr.back_button.isVisibleTo(host)
    hdr.back_button.click()
    assert calls == [1]
    host.set_back(None)
    assert not hdr.back_button.isVisibleTo(host)
    host.set_header("Title", "")
    assert not hdr.sub_label.isVisibleTo(host)
    host.set_header("Title", "Sub")
    assert hdr.sub_label.isVisibleTo(host)


def test_close_button_scrim_click_and_escape_close(qapp, reduced):
    win, host, *_ = _open(True)
    host.panel.header.close_button.click()
    assert not host.is_open()

    host.open(QWidget(), "#DAA520", "K")
    QTest.mouseClick(host.scrim, Qt.LeftButton, pos=QPoint(20, 300))
    assert not host.is_open()

    host.open(QWidget(), "#DAA520", "K")
    qapp.sendEvent(host.panel, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not host.is_open()


def test_clicks_inside_the_panel_do_not_close(qapp, reduced):
    win, host, *_ = _open(True)
    QTest.mouseClick(host.panel, Qt.LeftButton, pos=QPoint(300, 400))
    assert host.is_open()


def test_animation_slides_in_and_out(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    win = _Window()
    win.show()
    host = SlideSheetHost(win, is_dark=True)
    host.open(QWidget(), "#DAA520", "K")
    assert host.panel.x() >= 880 - 2           # starts off to the right
    QTest.qWait(SLIDE_MS + 150)
    assert host.panel.x() == 880 - SHEET_W
    assert host.scrim.opacity == pytest.approx(1.0)
    host.close()
    assert host.isVisible()                    # still sliding out
    QTest.qWait(SLIDE_MS + 150)
    assert not host.isVisible()
    win.close()


def test_reduced_motion_is_immediate(qapp, reduced):
    win = _Window()
    win.show()
    host = SlideSheetHost(win, is_dark=True)
    host.open(QWidget(), "#DAA520", "K")
    assert host.panel.x() == 880 - SHEET_W
    host.close()
    assert not host.isVisible()
    win.close()


def test_apply_theme_reaches_content(qapp, reduced):
    win, host, page, card, row = _open(True)
    calls = []

    class _C(QWidget):
        def apply_theme(self, is_dark):
            calls.append(is_dark)

    c = _C()
    host.open(c, "#DAA520", "K")
    host.apply_theme(False)
    assert calls[-1] is False
    assert host.panel._fill == m.qcolor(m.sheet_palette(False)["bg_app"])


# ── material parts ──────────────────────────────────────────────────────────

def test_toggle_metrics_and_colours(qapp, reduced):
    t = m.SheetToggle(False, "#ff9500", is_dark=True)
    assert (t.width(), t.height()) == (34, 20)
    t.setChecked(True)
    assert t._track_on == "#ff9500"
    img = t.grab().toImage()
    assert _near(img.pixelColor(5, 10), QColor("#ff9500"), 10)


def test_segmented_metrics_and_fill(qapp):
    s = m.SheetSegmented(["TTR", "CC"], "#DAA520", is_dark=True)
    assert s.height() == 28
    rects = s._seg_rects()
    assert rects[0].height() == 22 and rects[0].y() == 3
    s.resize(s.sizeHint())
    img = s.grab().toImage()
    r0 = rects[0]
    assert _near(img.pixelColor(int(r0.x()) + 4, int(r0.center().y())),
                 QColor("#DAA520"), 10)
    clicked = []
    s.index_changed.connect(clicked.append)
    QTest.mouseClick(s, Qt.LeftButton, pos=rects[1].center().toPoint())
    assert clicked == [1]


def test_icon_button_has_dimmed_disabled_icon(qapp):
    from utils.icon_factory import make_trash_icon
    b = m.IconButton(make_trash_icon(14, QColor("#ffffff")), "Delete", danger=True)
    from PySide6.QtGui import QIcon
    normal = b.icon().pixmap(14, 14, QIcon.Normal).toImage()
    disabled = b.icon().pixmap(14, 14, QIcon.Disabled).toImage()
    max_a = lambda im: max(im.pixelColor(x, y).alpha()
                           for y in range(im.height()) for x in range(im.width()))
    assert max_a(disabled) < max_a(normal) * 0.5
    assert (b.width(), b.height()) == (28, 28)


def test_sheet_row_keeps_inset_row_api(qapp):
    r = m.SheetRow("A", "b")
    r.add_control(QLabel("1"))
    r.add_control(QLabel("2"))
    r.set_row_disabled(True)
    assert not r.isEnabled()


def test_group_card_meta_and_rows(qapp):
    c = m.GroupCard("#DAA520", "Keysets", meta="3 shown")
    assert c.meta_label.text() == "3 shown"
    c.set_meta(None)
    assert not c.meta_label.isVisibleTo(c)
    a, b = QLabel("a"), QLabel("b")
    c.add_row(a)
    c.insert_row(0, b)
    assert c.rows() == [b, a]
    c.remove_row(b)
    assert c.rows() == [a]


# ── window-card corners ────────────────────────────────────────────────────

DESKTOP = QColor("#ff00ff")


class _Desktop(QWidget):
    """Stands in for what is behind a frameless window: magenta, so any
    pixel the sheet paints outside the rounded card shows."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), DESKTOP)
        p.end()


def _window_card(is_dark):
    """The launchpad window's rounded card, styled exactly as the window
    styles it (card_qss + window_edge_colors, radius 16, 1 px outline)."""
    from PySide6.QtWidgets import QVBoxLayout
    from utils.widgets.window_chrome_style import (
        RADIUS_NORMAL, card_qss, window_edge_colors,
    )
    bg = theme_manager.get_theme_colors(is_dark)["bg_app"]
    desk = _Desktop()
    desk.resize(880, 860)
    lay = QVBoxLayout(desk)
    lay.setContentsMargins(0, 0, 0, 0)
    card = QWidget(desk)
    card.setObjectName("app_card")
    card.setAttribute(Qt.WA_StyledBackground, True)
    card.setStyleSheet(card_qss("app_card", bg, RADIUS_NORMAL,
                                window_edge_colors(bg)["outline"]))
    lay.addWidget(card)
    return desk, card


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_sheet_keeps_the_window_cards_rounded_corners(qapp, reduced, theme):
    from utils.widgets.window_chrome_style import RADIUS_NORMAL, STROKE_INSET
    with _theme(qapp, theme):
        is_dark = theme == "dark"
        desk, card = _window_card(is_dark)
        host = SlideSheetHost(card, is_dark=is_dark, inset=STROKE_INSET,
                              bottom_radius=RADIUS_NORMAL - STROKE_INSET)
        host.open(QWidget(), "#DAA520", "K")
        desk.show()
        qapp.processEvents()
        img = desk.grab().toImage()
        W, H = 880, 860
        # The desktop still shows in both bottom corners, outside the curve.
        for x, y in ((0, H - 1), (2, H - 2), (4, H - 2), (2, H - 4),
                     (W - 1, H - 1), (W - 3, H - 2), (W - 5, H - 2), (W - 3, H - 4)):
            assert img.pixelColor(x, y) == DESKTOP, (x, y, img.pixelColor(x, y).name())
        # The card's 1 px outline stays visible on the left, right and bottom.
        outline_left = img.pixelColor(0, 600)
        outline_bottom = img.pixelColor(W - 100, H - 1)
        panel = m.qcolor(m.sheet_palette(is_dark)["bg_app"])
        assert not _near(outline_bottom, panel, 1)
        assert outline_left != DESKTOP
        # Just inside the curve the scrim and the panel are there.
        inside_left = img.pixelColor(RADIUS_NORMAL + 4, H - RADIUS_NORMAL - 4)
        assert inside_left != DESKTOP
        assert _near(img.pixelColor(W - RADIUS_NORMAL - 4, H - RADIUS_NORMAL - 4), panel)
        # Geometry: inside the stroke on three sides and under the header.
        assert host.geometry().left() == STROKE_INSET
        assert host.geometry().right() == W - 1 - STROKE_INSET
        assert host.geometry().bottom() == H - 1 - STROKE_INSET
        assert host.geometry().top() == HEADER_H + STROKE_INSET
        desk.close()


def test_square_frame_paints_the_corners(qapp, reduced):
    """The unrounded host (maximized window) does paint into the corners:
    proof the rounded test above would catch a square sheet."""
    desk, card = _window_card(True)
    host = SlideSheetHost(card, is_dark=True)
    host.open(QWidget(), "#DAA520", "K")
    desk.show()
    qapp.processEvents()
    img = desk.grab().toImage()
    assert img.pixelColor(879, 859) != DESKTOP
    assert host.mask().isEmpty()
    desk.close()


def test_set_frame_switches_between_rounded_and_square(qapp, reduced):
    from utils.widgets.window_chrome_style import RADIUS_NORMAL, STROKE_INSET
    desk, card = _window_card(True)
    desk.show()
    qapp.processEvents()
    host = SlideSheetHost(card, is_dark=True)
    host.set_frame(STROKE_INSET, RADIUS_NORMAL - STROKE_INSET)
    assert not host.mask().isEmpty()
    assert not host.mask().contains(QPoint(0, host.height() - 1))
    assert host.mask().contains(QPoint(host.width() // 2, host.height() - 1))
    host.set_frame(0, 0)
    assert host.mask().isEmpty()
    assert host.geometry().left() == 0
    desk.close()
