"""Failed-login material follows theme changes on an assembled roster card."""
from dataclasses import replace
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
from tests.test_grandstand_appearance_flow import _entry
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.roster_card import RosterCard


def test_light_fix_login_palette_has_darker_ink_and_border():
    light, dark = gp.fix_login(False), gp.fix_login(True)
    assert light['pill_text'] != dark['pill_text']
    assert QColor(light['pill_text']).lightness() < 128
    assert light['card_border'] != dark['card_border']
    assert light['card_border'].lightness() < dark['card_border'].lightness()


def test_card_restyles_fix_pill_and_painted_border_when_theme_changes(qapp):
    host = QWidget()
    host.resize(200, 260)
    host.setStyleSheet('background: white;')
    card = RosterCard(host)
    card.move(10, 10)
    card.set_entry(replace(_entry('failed'), login_failed=True))
    host.show()
    for dark in (False, True, False):
        card.apply_theme(dark)
        qapp.processEvents()
        material = gp.fix_login(dark)
        assert material['pill_text'] in card.fix_pill.styleSheet()
        assert material['pill_border'] in card.fix_pill.styleSheet()
        image = host.grab().toImage()
        actual = image.pixelColor(card.x(), card.y() + card.height() // 2)
        expected = material['card_border']
        assert max(abs(actual.red()-expected.red()), abs(actual.green()-expected.green()),
                   abs(actual.blue()-expected.blue())) <= 12
    host.close()
