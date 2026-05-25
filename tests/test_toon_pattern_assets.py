"""Tests for the pattern asset loader (load + tint + cache)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_load_returns_pixmap_for_known_pattern(qapp):
    from utils.toon_pattern_assets import tinted_pattern_pixmap
    pm = tinted_pattern_pixmap("dots", QColor("#ffffff"), tile_size=24)
    assert isinstance(pm, QPixmap)
    assert not pm.isNull()
    assert pm.width() == 24
    assert pm.height() == 24


def test_unknown_pattern_returns_null(qapp):
    from utils.toon_pattern_assets import tinted_pattern_pixmap
    pm = tinted_pattern_pixmap("not_a_pattern", QColor("#ffffff"), tile_size=24)
    assert pm.isNull()


def test_cache_returns_same_object(qapp):
    from utils.toon_pattern_assets import tinted_pattern_pixmap
    a = tinted_pattern_pixmap("dots", QColor("#abcdef"), tile_size=24)
    b = tinted_pattern_pixmap("dots", QColor("#abcdef"), tile_size=24)
    assert a is b


def test_cache_differentiates_by_color_and_size(qapp):
    from utils.toon_pattern_assets import tinted_pattern_pixmap
    a = tinted_pattern_pixmap("dots", QColor("#abcdef"), tile_size=24)
    b = tinted_pattern_pixmap("dots", QColor("#fedcba"), tile_size=24)
    c = tinted_pattern_pixmap("dots", QColor("#abcdef"), tile_size=48)
    assert a is not b
    assert a is not c


def test_known_pattern_names():
    from utils.toon_pattern_assets import PATTERN_NAMES
    assert PATTERN_NAMES == (
        "dots", "stripes_diag", "stripes_horiz", "plaid",
        "chevrons", "stars", "hearts", "waves",
    )
