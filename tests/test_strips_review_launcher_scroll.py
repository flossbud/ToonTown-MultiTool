"""A full compact launcher remains usable on a 720 logical pixel screen."""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_strips_controller import rig, settle
from utils.strips import layout as L
from utils.strips.launcher_port import LaunchAccount
from utils.strips.popovers.home import HomePanel, LAUNCH
from utils.strips.popovers.placement import LEFT


def wheel(card, point, delta):
    QApplication.sendEvent(card, QWheelEvent(
        QPointF(point), QPointF(card.mapToGlobal(point)), QPoint(), QPoint(0, delta),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


@pytest.mark.parametrize('style', ['neon', 'flat'])
@pytest.mark.parametrize('near_bottom', [False, True])
@pytest.mark.parametrize('scale', [1.0, 1.25, 1.5, 1.875])
def test_all_32_accounts_reachable_with_fixed_footer_on_720px_screen(rig, style, near_bottom, scale):
    _, controller, _ = rig()
    controller.set_style(style)
    strip = controller.follower.surface('101')
    strip.strip.set_scale(scale)
    strip.place((100, 50, 800, 600))
    if near_bottom:
        controller.follower.surface('101').place((100, 560, 800, 140))
    screen = QRect(0, 0, 1280, 720)
    controller.popovers._screen_rect = lambda _: screen
    accounts = tuple(LaunchAccount(str(i), 'ttr' if i < 16 else 'cc', f'Account {i}')
                     for i in range(32))
    card = HomePanel(style, scale=scale, accounts=accounts)
    card.set_view(LAUNCH)
    chosen = []
    card.launch_requested.connect(chosen.append)
    surface = controller.popovers.open_card('101', 'home', L.HOME, 0, card, align=LEFT)
    settle()
    assert screen.contains(surface.geometry())
    assert surface.height() <= 720
    footer = card.zone_rect('full')
    back = card.zone_rect('back')
    assert card.rect().contains(footer.toAlignedRect())
    assert card.rect().contains(back.toAlignedRect())
    viewport = card._to_widget(card._list_view)
    for _ in range(40):
        for i in range(32):
            rect = card.zone_rect('go', str(i))
            if rect is not None and viewport.contains(rect):
                QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, rect.center().toPoint())
        wheel(card, viewport.center().toPoint(), -120)
        assert card.zone_rect('full') == footer
        assert card.zone_rect('back') == back
    assert set(chosen) == {str(i) for i in range(32)}
    assert card._scroll_offset > 0
    wheel(card, viewport.center().toPoint(), 12000)
    assert card._scroll_offset == 0
