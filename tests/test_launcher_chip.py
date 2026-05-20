"""Tests for utils.launcher_chip — the shared chip-label dict."""

from utils.launcher_chip import LAUNCHER_CHIP_LABEL


def test_label_for_bottles():
    assert LAUNCHER_CHIP_LABEL["bottles"] == "BOTTLES"


def test_label_for_lutris():
    assert LAUNCHER_CHIP_LABEL["lutris"] == "LUTRIS"


def test_label_for_faugus():
    assert LAUNCHER_CHIP_LABEL["faugus"] == "FAUGUS"


def test_label_for_steam_proton():
    assert LAUNCHER_CHIP_LABEL["steam-proton"] == "STEAM"


def test_label_for_wine():
    assert LAUNCHER_CHIP_LABEL["wine"] == "WINE"


def test_label_for_native():
    assert LAUNCHER_CHIP_LABEL["native"] == "NATIVE"
