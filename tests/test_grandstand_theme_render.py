"""Grandstand widgets under the app's REAL stylesheet.

Every other grandstand test runs with no application stylesheet, so a plain
QWidget that inherits the app's `QWidget { background-color }` rule and paints
an opaque block over a custom-painted surface is invisible to them. This file
loads the actual theme and samples pixels.
"""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from utils import theme_manager
from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.card_shelf import CardShelf
from utils.widgets.grandstand.hero_stage import COPY_LEFT, HeroStage
from utils.widgets.grandstand.model import RosterEntry


def _distance(a, b):
    return (abs(a.red() - b.red()) + abs(a.green() - b.green())
            + abs(a.blue() - b.blue()))


@contextmanager
def _temporary_theme(qapp, theme):
    """Apply one real theme and restore the preceding application state."""
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


@pytest.fixture(params=["light", "dark"])
def themed_app(qapp, request):
    with _temporary_theme(qapp, request.param):
        yield qapp, request.param


def _render(widget, w, h):
    widget.resize(w, h)
    widget.show()
    QApplication.instance().processEvents()
    pm = QPixmap(w, h)
    pm.fill(Qt.magenta)          # a colour nothing legitimate paints
    widget.render(pm)
    return pm.toImage()


def _entry(account_id):
    return RosterEntry(
        account_id=account_id, game="ttr", label=f"L{account_id}",
        username=f"u{account_id}", toon_name=f"T{account_id}", species="cat",
        dna="7400", accent="#4a8fe7", footer="Primary",
        portrait_mode="render", state="idle", message="", raw_error="",
    )


def test_hero_copy_container_does_not_paint_the_app_background(themed_app):
    """The copy column must reveal the custom-painted hero below it."""
    _qapp, theme = themed_app
    hero = HeroStage()
    hero.set_game("ttr")
    img = _render(hero, 818, 232)
    # Inside copy, below every child: this is untouched hero artwork + scrim.
    probe = img.pixelColor(COPY_LEFT + 24, 200)
    base = gp.hero_base("ttr", theme == "dark")
    assert _distance(probe, base) < 60, (
        f"{theme}: copy container painted {probe.name()} over hero base "
        f"{base.name()}")
    hero.close()


def test_shelf_containers_do_not_paint_the_app_background(themed_app,
                                                           monkeypatch):
    """The head and gaps between cards must reveal the shelf panel."""
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None)
    _qapp, theme = themed_app
    shelf = CardShelf()
    shelf.set_entries([_entry("a"), _entry("b")])
    img = _render(shelf, 818, 300)
    panel = gp.panel(theme == "dark")["bg"]
    probes = {
        "head": img.pixelColor(400, 20),
        "strip": img.pixelColor(167, 162),
    }
    for area, probe in probes.items():
        assert _distance(probe, panel) < 10, (
            f"{theme}: shelf {area} painted {probe.name()} over panel "
            f"{panel.name()}")
    shelf.close()


def test_themed_app_fixture_restores_global_state(qapp):
    """Everything apply_theme touches must be back to its prior value."""
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    theme = "light" if before_marker == "dark" else "dark"

    with _temporary_theme(qapp, theme):
        assert theme_manager._APPLIED_THEME == theme

    assert qapp.styleSheet() == before_sheet
    assert qapp.palette() == before_palette
    assert theme_manager._APPLIED_THEME == before_marker


def test_disabled_play_keeps_its_translucency(qapp):
    """`.name()` drops alpha; all disabled Play colours must carry ARGB."""
    hero = HeroStage()
    hero.set_party([])
    assert hero.play_enabled() is False
    style = hero.play_button.styleSheet()
    colours = gp.play_button(False, True)
    for name in ("bg", "ink", "border"):
        expected = colours[name].name(QColor.HexArgb)
        assert expected in style
        assert len(expected) == 9
        assert expected.lower() != "#ffffffff"
    hero.close()
