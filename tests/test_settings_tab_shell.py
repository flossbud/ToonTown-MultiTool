"""Tests for the Sidebar widget -- category navigation rail."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


CATEGORIES = [
    ("general", "General"),
    ("games", "Games"),
    ("keep_alive", "Keep-Alive"),
    ("advanced", "Advanced"),
]


def test_sidebar_renders_each_category(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    assert len(sb.items) == 4
    assert [item.key for item in sb.items] == ["general", "games", "keep_alive", "advanced"]


def test_sidebar_default_active_is_first(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    assert sb.active_key == "general"


def test_sidebar_set_active_category(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    sb.set_active_category("keep_alive")
    assert sb.active_key == "keep_alive"


def test_sidebar_set_active_unknown_falls_back_to_general(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    sb.set_active_category("does_not_exist")
    assert sb.active_key == "general"


def test_sidebar_click_emits_category_selected(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    received = []
    sb.category_selected.connect(received.append)
    games_item = next(i for i in sb.items if i.key == "games")
    games_item.clicked.emit(games_item.key)
    assert received == ["games"]
    assert sb.active_key == "games"


def test_sidebar_clicking_active_item_does_not_re_emit(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    received = []
    sb.category_selected.connect(received.append)
    general_item = next(i for i in sb.items if i.key == "general")
    general_item.clicked.emit(general_item.key)
    assert received == []
    assert sb.active_key == "general"


def test_sidebar_active_item_paints_visible_accent(qapp):
    """The active item must paint a visibly-tinted background distinguishable
    from the resting sidebar background. Render to a QImage and inspect a
    pixel inside the item's body."""
    from PySide6.QtGui import QColor, QImage
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import Sidebar

    sb = Sidebar(CATEGORIES)
    sb.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    sb.resize(170, 200)
    sb.set_active_category("games")
    games_item = next(i for i in sb.items if i.key == "games")

    img = QImage(games_item.size(), QImage.Format_ARGB32)
    img.fill(0)
    games_item.render(img)

    # Sample a pixel well inside the item, away from the accent left border.
    # Use x=80 (safe within the item's ~100px layout width) at mid-height.
    # The sample should NOT match sidebar_bg (#111111); it should be lighter
    # by a perceptible amount because the active background overlay is on.
    sample = QColor(img.pixel(80, 18))
    sidebar_bg = QColor("#111111")
    # Allow for the overlay being semi-transparent: expect at least ~10
    # units brighter than the resting bg on any channel.
    assert sample.red() - sidebar_bg.red() >= 10, (
        f"active bg sample {sample.getRgb()} not perceptibly brighter than "
        f"sidebar_bg {sidebar_bg.getRgb()}"
    )


def test_sidebar_active_item_paints_accent_left_border(qapp):
    """The active item must paint a 3px accent-blue left border."""
    from PySide6.QtGui import QColor, QImage
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import Sidebar

    sb = Sidebar(CATEGORIES)
    sb.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    sb.resize(170, 200)
    sb.set_active_category("games")
    games_item = next(i for i in sb.items if i.key == "games")

    img = QImage(games_item.size(), QImage.Format_ARGB32)
    img.fill(0)
    games_item.render(img)

    # Sample a pixel inside the left border at x=1 (middle of the 3px border).
    sample = QColor(img.pixel(1, 18))
    accent = QColor("#0077ff")
    # Border is opaque accent color -- allow 30 units tolerance for AA.
    assert abs(sample.red() - accent.red()) < 30
    assert abs(sample.green() - accent.green()) < 30
    assert abs(sample.blue() - accent.blue()) < 30
