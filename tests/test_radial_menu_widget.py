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
    for key in ("accounts", "home", "settings", "close"):
        cx, cy, r = w.circle_geometry("main", key)
        w.activate_at(cx, cy)
    assert fired == ["accounts", "home", "settings", "close"]


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
