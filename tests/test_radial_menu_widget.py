import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="run under QT_QPA_PLATFORM=offscreen",
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_main_ring_emits_intents_on_hit():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    fired = []
    w.accounts_requested.connect(lambda: fired.append("accounts"))
    w.home_requested.connect(lambda: fired.append("home"))
    w.settings_requested.connect(lambda: fired.append("settings"))
    w.close_requested.connect(lambda: fired.append("close"))
    w.exit_requested.connect(lambda: fired.append("exit"))
    for key in ("accounts", "home", "settings", "close", "exit"):
        cx, cy, r = w.circle_geometry("main", key)
        w.activate_at(cx, cy)
    assert fired == ["accounts", "home", "settings", "close", "exit"]


def test_click_outside_any_circle_does_not_emit():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    fired = []
    w.close_requested.connect(lambda: fired.append("x"))
    w.activate_at(2, 2)
    assert fired == []


def test_paint_does_not_crash():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    pm = QPixmap(400, 400)
    p = QPainter(pm)
    w.render(p, QPoint(0, 0))   # exercises paintEvent paths without a live event loop
    p.end()


def test_accounts_state_lays_out_n_circles_and_emits_account_id():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    accts = [RingAccount(f"id{i}", "ttr", f"L{i}", f"T{i}", "", True, False) for i in range(8)]
    w.set_accounts(accts)
    assert w.state == "accounts"
    clicked = []
    w.account_clicked.connect(clicked.append)
    for i in range(8):
        cx, cy, r = w.circle_geometry("accounts", i)
        w.activate_at(cx, cy)
    assert clicked == [f"id{i}" for i in range(8)]


def test_back_returns_to_main_state():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False)])
    back = []
    w.back_requested.connect(lambda: back.append(1))
    cx, cy, r = w.circle_geometry("accounts", "back")
    w.activate_at(cx, cy)
    assert back == [1] and w.state == "main"


def _click_account(w, i):
    cx, cy, r = w.circle_geometry("accounts", i)
    w.activate_at(cx, cy)


def test_auto_close_only_after_last_account_launched():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False),
                    RingAccount("b", "ttr", "L", "T", "", True, False)])
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    _click_account(w, 0)
    assert closed == []          # one still un-launched -> stay open
    _click_account(w, 1)
    assert closed == [1]         # all launched -> auto-close the whole radial


def test_already_running_accounts_count_toward_all_launched():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    # index 1 is already running; launching index 0 completes the set.
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False),
                    RingAccount("b", "ttr", "L", "T", "", True, True)])
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    _click_account(w, 0)
    assert closed == [1]


def test_opening_all_running_ring_does_not_auto_close():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    # All already running: opening must NOT auto-close (no click happened).
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, True),
                    RingAccount("b", "ttr", "L", "T", "", True, True)])
    assert closed == []


def test_accounts_paint_does_not_crash():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", None, "", True, False),   # placeholder
                    RingAccount("b", "cc", "L2", "Toon", "", True, True)])
    w._hover = ("accounts", 0)   # exercise hover-label path
    pm = QPixmap(500, 500); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()


def test_reveal_order_is_left_to_right():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    order = w.reveal_order("main")
    xs = [w.circle_geometry("main", k)[0] for k in order]
    assert xs == sorted(xs)


def test_esc_emits_close():
    _app()
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert fired == [1]


def test_idle_timeout_is_15s():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160)
    assert w.idle_timeout_ms() == 15000


def test_idle_timer_wired_to_close():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160)
    assert w._idle_timer.isSingleShot()
    assert w._idle_timer.interval() == 15000
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w._idle_timer.timeout.emit()
    assert fired == [1]


def test_running_account_paints_status_dot():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "Toon", "", True, True)])
    # complete the reveal so the account paints
    for _ in range(len(w.reveal_order("accounts")) + 1):
        w._reveal_tick()
    img = QImage(500, 500, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); w.render(p, QPoint(0, 0)); p.end()
    # scan for a strongly-green pixel (the status dot)
    found = False
    for yy in range(0, 500, 2):
        for xx in range(0, 500, 2):
            c = img.pixelColor(xx, yy)
            if c.green() > 170 and c.green() - c.red() > 80 and c.green() - c.blue() > 60:
                found = True; break
        if found: break
    assert found, "running status dot (green) not painted"


def test_reveal_gates_painting_then_completes():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    # mid-reveal: nothing revealed yet -> paint must not crash
    pm = QPixmap(400, 400); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()
    # drive the reveal to completion deterministically (no event loop)
    for _ in range(len(w.reveal_order("main")) + 1):
        w._reveal_tick()
    assert w._reveal_active is False
    pm2 = QPixmap(400, 400); p2 = QPainter(pm2); w.render(p2, QPoint(0, 0)); p2.end()


def test_default_variant_is_transparent_five_spokes():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    assert sorted(w.reveal_order("main")) == sorted(
        ["accounts", "home", "settings", "close", "exit"])


def test_windowed_variant_has_three_spokes():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    assert sorted(w.reveal_order("main")) == sorted(["accounts", "transparent", "close"])


def test_windowed_variant_emits_per_spoke():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    fired = []
    w.accounts_requested.connect(lambda: fired.append("accounts"))
    w.transparent_requested.connect(lambda: fired.append("transparent"))
    w.close_requested.connect(lambda: fired.append("close"))
    for key in ("accounts", "transparent", "close"):
        cx, cy, r = w.circle_geometry("main", key)
        w.activate_at(cx, cy)
    assert fired == ["accounts", "transparent", "close"]


def test_windowed_transparent_spoke_is_top_center():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    cx, cy, r = w.circle_geometry("main", "transparent")
    # top-center: x == widget center x, y above center
    assert round(cx, 3) == round(w.width() / 2.0, 3)
    assert cy < w.height() / 2.0


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an active overlay + X display")
def test_controller_radial_open_close_smoke():
    # Live behavior (the controller hosting a click-accepting radial surface) is
    # validated manually on the packaged build; real X11 shaped surfaces are not
    # reliable headless. This documents the gap.
    pass
