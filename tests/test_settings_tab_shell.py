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
    games_item._on_clicked()
    assert received == ["games"]
    assert sb.active_key == "games"


def test_sidebar_clicking_active_item_does_not_re_emit(qapp):
    from tabs.settings_tab import Sidebar
    sb = Sidebar(CATEGORIES)
    received = []
    sb.category_selected.connect(received.append)
    general_item = next(i for i in sb.items if i.key == "general")
    general_item._on_clicked()
    assert received == []
