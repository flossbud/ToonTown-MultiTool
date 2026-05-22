"""Tests for ToonPortraitWidget's CC paint integration."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtGui import QImage

# Required before importing tabs.multitoon._tab because main.py imports
# can pull in the re-exec gate.
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from tabs.multitoon._tab import ToonPortraitWidget  # noqa: E402


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def overrides_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.cc_race_overrides_manager import CCRaceOverridesManager
    return CCRaceOverridesManager()


def _grab_image(widget, w: int, h: int) -> QImage:
    widget.resize(w, h)
    pm = widget.grab()
    return pm.toImage()


def test_cc_mode_with_silhouette_paints_complement_bg(qt_app, overrides_manager):
    w = ToonPortraitWidget(1)
    w.set_overrides_manager(overrides_manager)
    w.set_toon_name("Flossbud")
    w.set_cc_auto_species("DOG")
    # CC mode: red skin - paint_cc_badge draws an ellipse, not a rectangle,
    # so corners are left as the default widget background (gray).
    w.set_cc_mode(
        skin_rgb=(0.84, 0.19, 0.19),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )
    img = _grab_image(w, 96, 96)
    corner = img.pixelColor(1, 1)
    center = img.pixelColor(48, 48)
    # Corner (outside ellipse) should NOT be the skin/badge color.
    # Default widget bg is gray (~239). The red skin is rgb(214,48,48).
    # These should be clearly different: corner is lighter and less red.
    assert corner.red() > center.red() + 100 or corner.green() > center.green() + 100, (
        f"corner {corner.red()},{corner.green()},{corner.blue()} should differ from "
        f"center {center.red()},{center.green()},{center.blue()}"
    )
    # Center pixel should be non-gray - either skin color or complement bg.
    assert center.red() > 100 or center.green() > 100 or center.blue() > 100


def test_cc_mode_with_no_asset_falls_back_to_slot_number(qt_app, overrides_manager):
    w = ToonPortraitWidget(7)
    w.set_overrides_manager(overrides_manager)
    w.set_toon_name("UnknownToon")
    w.set_cc_auto_species("FROG")  # no frog.png exists yet
    w.set_cc_mode(
        skin_rgb=(0.5, 0.5, 0.5),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )
    img = _grab_image(w, 64, 64)
    # Center should have some white text mass (the "7").
    near_white = sum(
        1 for x in range(20, 44) for y in range(20, 44)
        if img.pixelColor(x, y).red() > 200
        and img.pixelColor(x, y).green() > 200
        and img.pixelColor(x, y).blue() > 200
    )
    assert near_white > 5, "expected slot-number text mass in fallback"


def test_override_wins_over_auto(qt_app, overrides_manager):
    w = ToonPortraitWidget(1)
    w.set_overrides_manager(overrides_manager)
    w.set_toon_name("Flossbud")
    w.set_cc_auto_species("DOG")
    overrides_manager.set("Flossbud", "cat")
    # Resolution: override "cat" > auto "DOG".
    assert w._resolve_asset_stem() == "cat"


def test_auto_used_when_no_override(qt_app, overrides_manager):
    w = ToonPortraitWidget(1)
    w.set_overrides_manager(overrides_manager)
    w.set_toon_name("Soupy")
    w.set_cc_auto_species("MOUSE")
    assert w._resolve_asset_stem() == "mouse"


def test_returns_none_when_unmapped_and_no_override(qt_app, overrides_manager):
    w = ToonPortraitWidget(1)
    w.set_overrides_manager(overrides_manager)
    w.set_toon_name("Mystery")
    w.set_cc_auto_species(None)
    assert w._resolve_asset_stem() is None
