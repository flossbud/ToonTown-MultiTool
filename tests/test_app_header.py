"""Tests for header construction in MultiToonTool.

We bypass MultiToonTool.__init__ (which starts background threads and reads
$HOME-rooted settings) by constructing via __new__ and calling the
_build_header method directly. The method only writes attributes onto self,
so the uninitialized instance is fine for this scope.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QLabel, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def header(qapp):
    """Build a header without running MultiToonTool.__init__."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    return instance._build_header()


def test_header_min_height_is_56(header):
    """Header minimum height grew from 48 to 56 to fit the 46px icon."""
    assert header.minimumHeight() == 56


def test_header_icon_widget_exists_with_expected_size(header):
    """The header has a child QLabel named 'header_icon' sized 46x46."""
    icon_label = header.findChild(QLabel, "header_icon")
    assert icon_label is not None, "header_icon QLabel not found in header"
    assert icon_label.size() == QSize(46, 46)


def test_header_icon_has_pixmap(header):
    """The header icon has a non-null pixmap loaded from _resolve_app_icon."""
    icon_label = header.findChild(QLabel, "header_icon")
    pixmap = icon_label.pixmap()
    assert not pixmap.isNull()


from PySide6.QtCore import Qt as _Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtCore import QPointF, QEvent


def _instance_with_nav_recorder(qapp):
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance._nav_select_calls = []
    instance.nav_select = lambda i: instance._nav_select_calls.append(i)
    return instance


def test_header_has_clickable_brand_link(qapp):
    instance = _instance_with_nav_recorder(qapp)
    header = instance._build_header()
    link = header.findChild(QWidget, "header_brand_link")
    assert link is not None
    assert link.cursor().shape() == _Qt.PointingHandCursor
    assert link.toolTip() == "About / Credits"


def test_clicking_brand_link_navigates_to_credits(qapp):
    instance = _instance_with_nav_recorder(qapp)
    header = instance._build_header()
    link = header.findChild(QWidget, "header_brand_link")
    dev = QPointingDevice.primaryPointingDevice()
    pos = QPointF(5, 5)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                        _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier, dev)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos,
                          _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier, dev)
    QApplication.sendEvent(link, press)
    QApplication.sendEvent(link, release)
    assert instance._nav_select_calls == [5]


def test_header_version_is_inline_text_not_pilled(qapp):
    """Version reads as subtle accent-colored text next to the title — no
    background fill, no rounded pill. Reverted from an earlier pilled
    version per UX feedback; this pins the inline style so the pill
    treatment doesn't accidentally come back."""
    from utils.theme_manager import get_theme_colors
    instance = _instance_with_nav_recorder(qapp)
    instance.header = instance._build_header()  # keep ref so children aren't GC'd

    instance._theme_colors = lambda: get_theme_colors(is_dark=True)
    c = instance._theme_colors()
    instance._set_header_title(c['header_text'], c['header_accent'])

    text = instance.title_label.text()
    assert "border-radius" not in text, (
        f"Version should be inline (no pill border-radius); got {text!r}"
    )
    assert "background" not in text, (
        f"Version should be inline (no background fill); got {text!r}"
    )


def test_header_brand_has_no_about_glyph(qapp):
    """The brand area is the clickable Credits affordance. An earlier
    cut added an 'ⓘ' glyph next to the title for visibility-at-rest;
    UX feedback rejected it. This pins the absence so the glyph doesn't
    accidentally come back."""
    instance = _instance_with_nav_recorder(qapp)
    header = instance._build_header()
    link = header.findChild(QWidget, "header_brand_link")
    assert link is not None
    glyph = link.findChild(QLabel, "header_about_glyph")
    assert glyph is None, (
        f"Expected no 'header_about_glyph' label inside the brand link; "
        f"found one with text {glyph.text()!r}"
    )
