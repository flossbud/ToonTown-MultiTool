"""Game selector: two cards, one active, art present, click emits."""
import os
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from utils.asset_paths import asset_path
from utils.widgets.grandstand import game_selector as game_selector_module
from utils.widgets.grandstand.game_selector import (
    ART, LOGO, GameCard, GameSelector, _desaturate,
)


def test_both_backdrops_and_logos_resolve():
    for name in list(ART.values()) + list(LOGO.values()):
        assert os.path.isfile(asset_path(name)), f"missing assets/{name}"


def test_defaults_to_ttr(qapp):
    assert GameSelector().active() == "ttr"


def test_set_active_switches(qapp):
    s = GameSelector()
    s.set_active("cc")
    assert s.active() == "cc"


def test_unknown_game_is_ignored(qapp):
    s = GameSelector()
    s.set_active("gamecube")
    assert s.active() == "ttr"


def test_counts_render_as_the_meta_line(qapp):
    s = GameSelector()
    s.set_counts(5, 3)
    assert s.card("ttr").meta_text() == "5 ACCOUNTS"
    assert s.card("cc").meta_text() == "3 ACCOUNTS"


def test_single_account_is_not_pluralised(qapp):
    s = GameSelector()
    s.set_counts(1, 0)
    assert s.card("ttr").meta_text() == "1 ACCOUNT"
    assert s.card("cc").meta_text() == "NO ACCOUNTS"


def test_clicking_the_inactive_card_emits(qapp):
    s = GameSelector()
    seen = []
    s.game_clicked.connect(seen.append)
    QTest.mouseClick(s.card("cc"), Qt.LeftButton, pos=QPoint(20, 20))
    assert seen == ["cc"]


def test_clicking_the_active_card_still_emits(qapp):
    """The view decides whether a re-select is a no-op, not the widget."""
    s = GameSelector()
    seen = []
    s.game_clicked.connect(seen.append)
    QTest.mouseClick(s.card("ttr"), Qt.LeftButton, pos=QPoint(20, 20))
    assert seen == ["ttr"]


def test_art_is_clipped_to_the_rounded_card(qapp):
    parent = QWidget()
    parent.resize(420, 92)
    background = QColor(3, 7, 11)
    parent_palette = parent.palette()
    parent_palette.setColor(QPalette.Window, background)
    parent.setPalette(parent_palette)
    parent.setAutoFillBackground(True)

    card = GameCard("ttr", parent)
    card.setGeometry(10, 10, 400, 72)
    rendered = QImage(parent.size(), QImage.Format_ARGB32_Premultiplied)
    rendered.fill(Qt.transparent)
    parent.render(rendered)

    assert rendered.pixelColor(11, 11) == background
    assert rendered.pixelColor(15, 15) != background


@pytest.mark.parametrize("amount", [0.44, 0.45])
def test_large_art_desaturates_without_a_startup_stall(qapp, amount):
    art = QPixmap(asset_path(ART["cc"]))

    started = perf_counter()
    dimmed = _desaturate(art, amount)
    elapsed = perf_counter() - started

    assert not dimmed.isNull()
    assert elapsed < 0.1, f"desaturation took {elapsed:.3f}s"


def test_desaturation_reduces_channel_spread_and_preserves_alpha(qapp):
    source = QImage(3, 1, QImage.Format_RGBA8888)
    for x, color in enumerate((
            QColor(255, 0, 0, 64),
            QColor(0, 255, 0, 123),
            QColor(0, 0, 255, 224))):
        source.setPixelColor(x, 0, color)
    art = QPixmap.fromImage(source)
    before = [art.toImage().pixelColor(x, 0) for x in range(3)]
    result = _desaturate(art, 0.45).toImage()
    after = [result.pixelColor(x, 0) for x in range(3)]

    assert after != before
    for source_color, dimmed_color in zip(before, after):
        source_spread = max(
            source_color.red(), source_color.green(), source_color.blue()
        ) - min(source_color.red(), source_color.green(), source_color.blue())
        dimmed_spread = max(
            dimmed_color.red(), dimmed_color.green(), dimmed_color.blue()
        ) - min(dimmed_color.red(), dimmed_color.green(), dimmed_color.blue())
        assert dimmed_spread < source_spread
    assert [color.alpha() for color in after] == [
        color.alpha() for color in before
    ]


def test_translucent_pixels_receive_the_same_desaturation_as_opaque(qapp):
    source = QImage(2, 1, QImage.Format_RGBA8888)
    source.setPixelColor(0, 0, QColor(255, 0, 0, 255))
    source.setPixelColor(1, 0, QColor(255, 0, 0, 64))

    result = _desaturate(QPixmap.fromImage(source), 0.45).toImage()
    opaque = result.pixelColor(0, 0)
    translucent = result.pixelColor(1, 0)

    assert translucent.alpha() == 64
    assert abs(translucent.red() - opaque.red()) <= 2
    assert abs(translucent.green() - opaque.green()) <= 2
    assert abs(translucent.blue() - opaque.blue()) <= 2


def test_card_reads_inactive_saturation_from_palette(qapp, monkeypatch):
    original_game_card = game_selector_module.gp.game_card
    inactive_lookups = []

    def game_card_with_tuned_saturation(game, active, is_dark):
        colors = original_game_card(game, active, is_dark)
        if not active:
            inactive_lookups.append((game, active, is_dark))
            colors["saturation"] = 0.73
        return colors

    seen = []
    monkeypatch.setattr(
        game_selector_module.gp, "game_card", game_card_with_tuned_saturation)
    monkeypatch.setattr(
        game_selector_module, "_desaturate",
        lambda pixmap, amount: (seen.append(amount), pixmap)[1])

    card = GameCard("ttr")
    card.apply_theme(False)

    assert inactive_lookups == [("ttr", False, True)]
    assert seen == [0.73]


def test_nearly_untouched_desaturation_returns_source(qapp):
    art = QPixmap(2, 2)
    art.fill(QColor(255, 0, 0))

    assert _desaturate(art, 0.999) is art


def test_null_pixmap_desaturation_returns_source(qapp):
    art = QPixmap()

    assert _desaturate(art, 0.45) is art


def test_selector_constructs_without_a_startup_stall(qapp):
    started = perf_counter()
    selector = GameSelector()
    elapsed = perf_counter() - started

    assert selector.active() == "ttr"
    assert elapsed < 0.1, f"GameSelector construction took {elapsed:.3f}s"
