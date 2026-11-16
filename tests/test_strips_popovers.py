"""Popover pieces: placement, the outside-click watch, counters and menus."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest

from utils.strips import tokens
from utils.strips.popovers.counters import CountersModel, CountersView
from utils.strips.popovers.menu import MenuItem, PillMenu
from utils.strips.popovers.placement import LEFT, place_popover
from utils.strips.popovers.pointer_watch import PointerWatch

SCREEN = QRect(0, 0, 1920, 1080)
MAGENTA = QColor(255, 0, 255)


def close(a, b, tolerance=4):
    b = QColor(b)
    return (abs(a.red() - b.red()) <= tolerance
            and abs(a.green() - b.green()) <= tolerance
            and abs(a.blue() - b.blue()) <= tolerance)


# -- placement ------------------------------------------------------------------

def test_drops_down_centred_on_its_anchor():
    spot = place_popover(QRect(500, 100, 28, 28), QSize(120, 80), SCREEN, gap=5)
    assert spot.pos == QPoint(500 + 14 - 60, 100 + 28 + 5)
    assert not spot.flipped and spot.caret_x == 60


def test_left_aligned_panel():
    spot = place_popover(QRect(500, 100, 28, 28), QSize(236, 200), SCREEN,
                         gap=10, align=LEFT)
    assert spot.pos == QPoint(500, 138)
    assert spot.caret_x == 14


def test_clamped_to_the_screen_edges_and_the_caret_still_points_at_the_anchor():
    spot = place_popover(QRect(10, 100, 28, 28), QSize(200, 80), SCREEN, gap=5)
    assert spot.pos.x() == 4
    assert spot.caret_x == 10 + 14 - 4
    spot = place_popover(QRect(1880, 100, 28, 28), QSize(200, 80), SCREEN, gap=5)
    assert spot.pos.x() == 1920 - 4 - 200
    assert spot.caret_x == 1880 + 14 - spot.pos.x()


def test_flips_above_only_when_there_is_no_room_below():
    anchor = QRect(500, 1000, 28, 28)
    spot = place_popover(anchor, QSize(200, 120), SCREEN, gap=5)
    assert spot.flipped and spot.pos.y() == 1000 - 5 - 120
    # Room below: never flips, however much room there is above.
    assert not place_popover(QRect(500, 600, 28, 28), QSize(200, 120), SCREEN).flipped


def test_no_room_either_way_stays_on_the_screen():
    small = QRect(0, 0, 400, 150)
    spot = place_popover(QRect(100, 60, 28, 28), QSize(200, 120), small, gap=5)
    assert not spot.flipped
    assert small.contains(QRect(spot.pos, QSize(200, 120)))


def test_other_screens_have_their_own_origin():
    right = QRect(1920, 0, 1920, 1080)
    spot = place_popover(QRect(1925, 100, 28, 28), QSize(200, 80), right, gap=5)
    assert spot.pos.x() == 1924


# -- outside clicks and Escape -----------------------------------------------------

class Probe:
    def __init__(self):
        self.down = False
        self.escapes = 0
        self.grabbed = []

    def buttons_down(self):
        return self.down

    def grab_escape(self, on):
        self.grabbed.append(on)

    def escape_pressed(self):
        hit, self.escapes = self.escapes > 0, 0
        return hit

    def close(self):
        pass


@pytest.fixture
def watch(qapp):
    probe = Probe()
    cursor = {"pos": QPoint(0, 0)}
    w = PointerWatch(probe, lambda: cursor["pos"])
    events = []
    w.pressed_outside.connect(lambda: events.append("outside"))
    w.escape.connect(lambda: events.append("escape"))
    yield w, probe, cursor, events
    w.shutdown()


INSIDE = QRect(100, 100, 50, 50)


def test_a_press_outside_is_reported_once_per_press(watch):
    w, probe, cursor, events = watch
    w.watch(INSIDE.contains)
    cursor["pos"] = QPoint(500, 500)
    probe.down = True
    w.tick(), w.tick(), w.tick()          # held: one press, not three
    assert events == ["outside"]
    probe.down = False
    w.tick()
    probe.down = True
    w.tick()
    assert events == ["outside", "outside"]


def test_a_press_inside_is_not_elsewhere(watch):
    w, probe, cursor, events = watch
    w.watch(INSIDE.contains)
    cursor["pos"] = QPoint(120, 120)
    probe.down = True
    w.tick()
    assert events == []


def test_the_click_that_opened_the_popover_does_not_close_it(watch):
    w, probe, cursor, events = watch
    probe.down = True                      # still held when the watch starts
    cursor["pos"] = QPoint(500, 500)
    w.watch(INSIDE.contains)
    w.tick()
    assert events == []
    probe.down = False
    w.tick()
    assert events == []


def test_escape_is_grabbed_only_while_watching(watch):
    w, probe, cursor, events = watch
    w.watch(INSIDE.contains)
    assert probe.grabbed == [True]
    probe.escapes = 1
    w.tick()
    assert events == ["escape"]
    w.stop()
    assert probe.grabbed == [True, False]
    assert not w.is_watching()


def test_a_key_capture_takes_escape_away_from_the_watch(watch):
    w, probe, cursor, events = watch
    w.watch(INSIDE.contains)
    w.pause_escape(True)
    assert probe.grabbed[-1] is False
    probe.escapes = 1
    w.tick()
    assert events == []
    w.pause_escape(False)
    assert probe.grabbed[-1] is True


# -- counters ---------------------------------------------------------------------

def render(widget, method):
    size = widget.sizeHint()
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(MAGENTA)
    p = QPainter(image)
    getattr(widget, method)(p)
    p.end()
    return image


def test_counter_cells_and_thousands_separators(qapp):
    view = CountersView()
    view.set_model(CountersModel(beans=456, bank=12840, tokens=None))
    texts = [t for kind, _r, t in view._parts if kind == "text"]
    assert texts == ["456", "12,840"]
    kinds = [kind for kind, _r, _t in view._parts if kind != "text"]
    assert kinds == ["bean", "jar"]
    narrow = view.sizeHint().width()
    view.set_model(CountersModel(beans=456, bank=12840, tokens=310))
    assert [k for k, _r, _t in view._parts if k != "text"] == ["bean", "jar", "token"]
    assert view.sizeHint().width() > narrow
    view.set_model(CountersModel(beans=None, bank=None))
    assert [t for kind, _r, t in view._parts if kind == "text"] == ["\u2013", "\u2013"]


def test_collapsed_name_leads_the_counters(qapp):
    view = CountersView()
    view.set_model(CountersModel(beans=250, bank=6979, name="Linux"))
    assert view._parts[0][0] == "name" and view._parts[0][2] == "Linux"


def test_neon_counters_are_a_pill_and_flat_counters_are_bare(qapp):
    view = CountersView()
    view.set_model(CountersModel(beans=456, bank=12840))
    image = render(view, "render_counters")
    pill = view.pill_rect()
    inside = image.pixelColor(int(pill.x() + 6), int(pill.center().y()))
    assert inside != MAGENTA and inside.green() < 110        # dark glass over magenta
    assert image.pixelColor(2, int(pill.center().y())) == MAGENTA
    view.set_style("flat")
    image = render(view, "render_counters")
    lock = view.lock_rect()
    # Bare text: just left of the lock there is no pill behind the gap.
    assert image.pixelColor(int(lock.x() - 3), int(lock.y() + 1)) == MAGENTA


def test_lock_shows_its_state_in_the_toon_colour(qapp):
    view = CountersView()
    view.set_style("flat")
    view.set_model(CountersModel(beans=1, bank=2, locked=True, accent="#56c856"))
    lock = view.lock_rect()
    image = render(view, "render_counters")
    assert close(image.pixelColor(int(lock.x() + 2), int(lock.y() + 2)), "#56c856")
    assert view.lock_tooltip() == "Unlock: show on hover only"
    view.set_model(CountersModel(beans=1, bank=2, locked=False, accent="#56c856"))
    image = render(view, "render_counters")
    assert not close(image.pixelColor(int(lock.x() + 2), int(lock.y() + 2)), "#56c856")
    assert view.lock_tooltip() == "Lock: keep counters shown"


def test_hover_area_reaches_up_to_the_strip(qapp):
    """The gap above the counters belongs to them, so the pointer can come
    down from the name without the counters closing."""
    view = CountersView()
    view.set_model(CountersModel(beans=456, bank=12840))
    area = view.input_rects()[0]
    assert area.top() == 0
    assert area.contains(view.lock_rect().center().toPoint())
    assert area.bottom() <= view.height()


def test_lock_click_and_scale(qapp):
    view = CountersView()
    view.set_scale(1.25)
    view.set_model(CountersModel(beans=456, bank=12840))
    assert view.lock_rect().width() == pytest.approx(22.5)
    hits = []
    view.lock_clicked.connect(lambda: hits.append(1))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                     view.lock_rect().center().toPoint())
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(12, 14))   # a cell
    assert hits == [1]


# -- pill menus -------------------------------------------------------------------

ITEMS = [MenuItem("edit", "Edit keyset"), MenuItem("hide", "Hide keyset", disabled=True)]


def test_menu_pills_are_centred_and_report_their_key(qapp):
    menu = PillMenu(ITEMS, "#E05252")
    a, b = menu.pill_rect(0), menu.pill_rect(1)
    assert a.center().x() == pytest.approx(b.center().x())
    assert b.top() - a.bottom() == pytest.approx(4.0)
    assert a.height() == pytest.approx(23.0)
    chosen = []
    menu.chosen.connect(chosen.append)
    QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier, a.center().toPoint())
    assert chosen == ["edit"]


def test_disabled_item_does_nothing(qapp):
    menu = PillMenu(ITEMS, "#E05252")
    chosen = []
    menu.chosen.connect(chosen.append)
    QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier,
                     menu.pill_rect(1).center().toPoint())
    assert chosen == []


def test_only_the_pills_take_the_pointer(qapp):
    menu = PillMenu(ITEMS, "#E05252")
    rects = menu.input_rects()
    assert len(rects) == 2
    assert not any(r.contains(QPoint(menu.width() // 2, 2)) for r in rects)   # caret


def test_menu_paint_in_both_looks(qapp):
    for look, fill in (("neon", None), ("flat", tokens.POPOVER_BASE)):
        menu = PillMenu(ITEMS, "#E05252", look)
        image = render(menu, "render_menu")
        pill = menu.pill_rect(0)
        # Caret in the anchor colour, at the top centre.
        assert close(image.pixelColor(menu.width() // 2, 3), "#E05252")
        # Border in the anchor colour.
        assert close(image.pixelColor(int(pill.center().x()), int(pill.top() + 1)), "#E05252")
        body = image.pixelColor(int(pill.x() + 8), int(pill.top() + 5))
        if fill:
            assert close(body, fill)
        else:
            assert body.red() > 2 * body.green() and body.red() < 0x50   # body(c)
    # Neon pills glow; flat ones do not.
    neon = render(PillMenu(ITEMS, "#E05252", "neon"), "render_menu")
    flat_menu = PillMenu(ITEMS, "#E05252", "flat")
    flat = render(flat_menu, "render_menu")
    pill = flat_menu.pill_rect(0)
    spot = (int(pill.center().x()), int(pill.top() - 2))
    assert neon.pixelColor(*spot) != MAGENTA
    assert flat.pixelColor(*spot) == MAGENTA


def test_checked_item_is_wider_by_its_check(qapp):
    plain = PillMenu([MenuItem("lock", "Lock counters")], "#4a8fe7")
    checked = PillMenu([MenuItem("lock", "Lock counters", checked=True)], "#4a8fe7")
    assert checked.pill_rect(0).width() == pytest.approx(plain.pill_rect(0).width() + 12)


def test_caret_follows_a_clamped_menu(qapp):
    menu = PillMenu(ITEMS, "#E05252", "flat")
    menu.set_caret_x(20)
    image = render(menu, "render_menu")
    assert close(image.pixelColor(20, 3), "#E05252")
    assert image.pixelColor(menu.width() // 2, 2) == MAGENTA


# -- keyset editor card -------------------------------------------------------------

from utils import logical_actions                                      # noqa: E402
from utils.strips.popovers.editor import (EditorModel, KeysetEditor,   # noqa: E402
                                          key_name)

TTR_ACTIONS = tuple((a, logical_actions.ACTION_LABELS[a])
                    for a in logical_actions.actions_for("ttr"))
BINDS = (("forward", "w"), ("reverse", "s"), ("left", "a"), ("right", "d"),
         ("jump", "space"), ("book", "]"), ("gags", "g"), ("tasks", "t"),
         ("map", "Shift_L"), ("action", "BackSpace"))
MODEL = EditorModel(1, TTR_ACTIONS, BINDS)


def test_key_names_fit_a_keycap():
    assert key_name("w") == "W"
    assert key_name("space") == "Space"
    assert key_name("BackSpace") == "Bksp"
    assert key_name("Shift_L") == "Shift"
    assert key_name("Up") == "↑"
    assert key_name("") == "–"
    assert key_name("F5") == "F5"


def test_list_layout_is_two_columns_of_the_games_actions(qapp):
    card = KeysetEditor(MODEL, "list")
    assert card.card_rect().width() == pytest.approx(266.0)
    caps = [card.zone_rect("cap", a) for a, _l in TTR_ACTIONS]
    assert all(c is not None for c in caps)
    # Five rows, 22 px apart; the sixth action starts the second column.
    assert caps[1].center().y() - caps[0].center().y() == pytest.approx(22.0)
    assert caps[5].center().y() == pytest.approx(caps[0].center().y())
    assert caps[5].right() > caps[0].right() + 100
    assert caps[0].height() == pytest.approx(18.0) and caps[0].width() >= 20.0
    assert card.zone_rect("key", "w") is None            # no keyboard in List


def test_keys_layout_has_the_small_keyboard(qapp):
    card = KeysetEditor(MODEL, "keys")
    q, a, z = (card.zone_rect("key", k) for k in "qaz")
    assert q.width() == pytest.approx(18.0)
    assert a.left() - q.left() == pytest.approx(9.0)      # row offsets 0 / 9 / 18
    assert z.left() - q.left() == pytest.approx(18.0)
    one, equals = card.zone_rect("key", "1"), card.zone_rect("key", "=")
    inner = card.card_rect().adjusted(14, 0, -14, 0)
    assert one.left() == pytest.approx(inner.left())
    assert equals.right() == pytest.approx(inner.right())  # the row fills the card
    space, bksp = card.zone_rect("key", "space"), card.zone_rect("key", "BackSpace")
    assert bksp.right() == pytest.approx(inner.right())
    assert space.width() > 40
    assert card.sizeHint().height() > KeysetEditor(MODEL, "list").sizeHint().height()


def test_keys_layout_shows_bound_keys_and_the_selected_one(qapp):
    card = KeysetEditor(MODEL, "keys", "flat")
    image = render(card, "render_editor")

    def at(code):
        r = card.zone_rect("key", code)
        return image.pixelColor(int(r.x() + 3), int(r.y() + 3))

    assert close(at("w"), "#4A8FE7")                       # Forward's key, solid
    tinted = at("s")                                       # bound in this set
    assert tinted.blue() > tinted.red() + 20 and not close(tinted, "#4A8FE7")
    assert close(at("q"), "#2e2e2e")                       # unbound


def test_card_paint_in_both_looks(qapp):
    flat = KeysetEditor(MODEL, "list", "flat")
    image = render(flat, "render_editor")
    card = flat.card_rect()
    assert close(image.pixelColor(int(card.x() + 30), int(card.bottom() - 6)), "#161616")
    assert close(image.pixelColor(int(card.center().x()), int(card.bottom() - 1)), "#4A8FE7")
    assert image.pixelColor(int(card.x() - 6), int(card.center().y())) == MAGENTA
    neon = KeysetEditor(MODEL, "list", "neon")
    image = render(neon, "render_editor")
    body = image.pixelColor(int(card.x() + 30), int(card.bottom() - 6))
    assert body.blue() > body.red() and body.blue() < 0x50   # dk(c, 24..11)
    assert image.pixelColor(int(card.x() - 6), int(card.center().y())) != MAGENTA  # halo


def test_conflicting_keycaps_are_red_and_the_note_makes_the_card_taller(qapp):
    clash = EditorModel(1, TTR_ACTIONS, BINDS[:4] + (("jump", "w"),) + BINDS[5:],
                        frozenset({"forward", "jump"}), "W is used by Forward and Jump")
    card = KeysetEditor(clash, "list", "flat")
    assert card.sizeHint().height() > KeysetEditor(MODEL, "list", "flat").sizeHint().height()
    image = render(card, "render_editor")
    cap = card.zone_rect("cap", "jump")
    assert close(image.pixelColor(int(cap.center().x()), int(cap.y())), "#e05252", 12)
    fine = card.zone_rect("cap", "left")
    assert close(image.pixelColor(int(fine.center().x()), int(fine.y())), "#444444", 12)


def test_only_the_card_takes_the_pointer(qapp):
    card = KeysetEditor(MODEL, "list")
    rects = card.input_rects()
    assert rects == [card.card_rect().toAlignedRect()]
    assert not rects[0].contains(QPoint(3, 3))


def test_close_and_layout_switch(qapp):
    card = KeysetEditor(MODEL, "list")
    closed, kinds = [], []
    card.close_requested.connect(lambda: closed.append(1))
    card.layout_changed.connect(kinds.append)
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("kind", "keys").center().toPoint())
    assert card.kind() == "keys" and kinds == ["keys"]
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("close").center().toPoint())
    assert closed == [1]


def test_listening_keycap_and_a_second_click_cancels(qapp):
    from PySide6.QtWidgets import QWidget
    card = KeysetEditor(MODEL, "list")
    card.show()
    states = []
    card.capture_changed.connect(states.append)
    spot = card.zone_rect("cap", "left").center().toPoint()
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, spot)
    assert card.listening() == "left" and QWidget.keyboardGrabber() is card
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect("cap", "left").center().toPoint())
    assert card.listening() == "" and QWidget.keyboardGrabber() is None
    assert states == [True, False]
    card.hide()
    card.deleteLater()


def test_a_key_with_no_name_keeps_waiting_and_named_keys_bind(qapp):
    card = KeysetEditor(MODEL, "list")
    card.show()
    bound = []
    card.bind_requested.connect(lambda a, k: bound.append((a, k)))
    card.begin_capture("map")
    QTest.keyClick(card, Qt.Key_unknown)
    assert card.listening() == "map" and bound == []
    QTest.keyClick(card, Qt.Key_Space)
    assert bound == [("map", "space")] and card.listening() == ""
    card.begin_capture("book")
    QTest.keyClick(card, Qt.Key_Up)
    assert bound[-1] == ("book", "Up")
    card.hide()
    card.deleteLater()


def test_hiding_the_card_mid_capture_releases_the_keyboard(qapp):
    from PySide6.QtWidgets import QWidget
    from utils import chord_capture_state
    card = KeysetEditor(MODEL, "list")
    card.show()
    card.begin_capture("jump")
    assert chord_capture_state.is_active()
    card.hide()
    assert QWidget.keyboardGrabber() is None
    assert not chord_capture_state.is_active()
    card.deleteLater()


# -- home panel -------------------------------------------------------------------

from utils.strips.launcher_port import LaunchAccount, as_account, read_accounts  # noqa: E402
from utils.strips.popovers.home import HomePanel                              # noqa: E402

ACCOUNTS = (LaunchAccount("1", "ttr", "Main", "running", "Flossbud"),
            LaunchAccount("2", "ttr", "Alt 3"),
            LaunchAccount("3", "cc", "Clash alt", "launching"))


def test_launcher_port_accepts_objects_and_dicts():
    class Thing:
        account_id, game, label, state, toon = 7, "cc", "Clash", "running", None

    assert as_account(Thing()) == LaunchAccount("7", "cc", "Clash", "running", "")
    assert as_account({"account_id": "x", "game": "ttr", "label": "A",
                       "state": "nonsense"}).state == "idle"

    class Port:
        def accounts(self):
            raise RuntimeError("launcher not ready")

    assert read_accounts(Port()) == () and read_accounts(None) == ()


def test_quick_menu_is_236_wide_with_five_rows(qapp):
    panel = HomePanel("neon", accounts=ACCOUNTS)
    assert panel.card_rect().width() == pytest.approx(236.0)
    rows = [panel.zone_rect("row", k) for k in ("launch", "settings", "window",
                                                 "toggle", "quit")]
    assert all(r is not None and r.height() == pytest.approx(34.0) for r in rows)
    assert rows[3].top() - rows[2].bottom() > 10        # the divider sits between
    assert panel.rows()[0][3] == "1 running ›"


def test_compact_launcher_is_260_wide_and_only_idle_accounts_have_a_button(qapp):
    panel = HomePanel("neon", accounts=ACCOUNTS)
    panel.set_view("launch")
    assert panel.card_rect().width() == pytest.approx(260.0)
    assert panel.zone_rect("go", "1") is None           # running
    assert panel.zone_rect("go", "3") is None           # launching
    button = panel.zone_rect("go", "2")
    assert button is not None and button.height() == pytest.approx(24.0)
    assert panel.zone_rect("back") is not None and panel.zone_rect("full") is not None


def test_home_panel_paint_in_both_looks(qapp):
    for look in ("neon", "flat"):
        panel = HomePanel(look, accounts=ACCOUNTS)
        image = render(panel, "render_panel")
        card = panel.card_rect()
        edge = image.pixelColor(int(card.center().x()), int(card.bottom() - 1))
        assert close(edge, "#0077ff"), look
        row = panel.zone_rect("row", "launch")
        icon = image.pixelColor(int(row.left() + 6 + 5), int(row.center().y() - 7))
        assert close(icon, "#E05252", 30), look          # the red power block
        halo = image.pixelColor(int(card.left() - 6), int(card.center().y()))
        assert (halo != MAGENTA) == (look == "neon")
        panel.set_view("launch")
        image = render(panel, "render_panel")
        button = panel.zone_rect("go", "2")
        assert close(image.pixelColor(int(button.center().x()), int(button.top() + 4)),
                     "#4A8FE7", 30), look


def test_stopped_service_offers_start(qapp):
    panel = HomePanel("flat", running=False)
    assert [label for key, _c, label, _h in panel.rows() if key][3] == "Start all toons"
    panel.set_running(True)
    assert [label for key, _c, label, _h in panel.rows() if key][3] == "Stop all toons"
