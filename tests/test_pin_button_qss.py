# tests/test_pin_button_qss.py
from tabs.multitoon._tab import (
    _pin_toggle_qss, _pin_ka_off_qss, _pin_ka_on_qss, _pin_cs_chip_qss,
)


def test_toggle_on_state_has_hover():
    qss = _pin_toggle_qss("#3ec46a", True)
    assert ":hover" in qss


def test_toggle_off_state_still_has_hover():
    assert ":hover" in _pin_toggle_qss("#3ec46a", False)


def test_keep_alive_off_has_hover():
    assert ":hover" in _pin_ka_off_qss()


def test_keep_alive_on_has_hover():
    assert ":hover" in _pin_ka_on_qss("#e8922e", "#f0a050")


def test_click_sync_chip_has_hover():
    assert ":hover" in _pin_cs_chip_qss("#d6406f")
