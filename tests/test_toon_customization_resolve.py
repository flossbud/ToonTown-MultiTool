"""Tests for the customization resolver helpers."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QBrush, QColor, QGradient
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- resolve_portrait_brush ------------------------------------------------

def test_portrait_brush_solid_color(qapp):
    from utils.toon_customization_resolve import resolve_portrait_brush
    entry = {"portrait": {"color": "#abcdef"}}
    brush = resolve_portrait_brush(entry, QColor("#000000"))
    assert isinstance(brush, QBrush)
    assert brush.color() == QColor("#abcdef")


def test_portrait_brush_gradient_overrides_color(qapp):
    from utils.toon_customization_resolve import resolve_portrait_brush
    entry = {"portrait": {
        "color": "#abcdef",
        "gradient": {"start": "#ff0000", "end": "#00ff00"},
    }}
    brush = resolve_portrait_brush(entry, QColor("#000000"))
    grad = brush.gradient()
    assert grad is not None
    assert grad.type() == QGradient.LinearGradient
    stops = grad.stops()
    assert stops[0][1] == QColor("#ff0000")
    assert stops[-1][1] == QColor("#00ff00")


def test_portrait_brush_missing_uses_fallback(qapp):
    from utils.toon_customization_resolve import resolve_portrait_brush
    brush = resolve_portrait_brush({}, QColor("#123456"))
    assert brush.color() == QColor("#123456")


def test_portrait_brush_null_color_uses_fallback(qapp):
    from utils.toon_customization_resolve import resolve_portrait_brush
    entry = {"portrait": {"color": None}}
    brush = resolve_portrait_brush(entry, QColor("#123456"))
    assert brush.color() == QColor("#123456")


# -- resolve_portrait_pattern ----------------------------------------------

def test_portrait_pattern_returns_name_and_color(qapp):
    from utils.toon_customization_resolve import resolve_portrait_pattern
    entry = {"portrait": {"pattern": {"name": "dots", "color": "#ffffff"}}}
    result = resolve_portrait_pattern(entry)
    assert result == ("dots", QColor("#ffffff"))


def test_portrait_pattern_missing_returns_none(qapp):
    from utils.toon_customization_resolve import resolve_portrait_pattern
    assert resolve_portrait_pattern({}) is None
    assert resolve_portrait_pattern({"portrait": {}}) is None
    assert resolve_portrait_pattern({"portrait": {"pattern": None}}) is None


# -- resolve_accent --------------------------------------------------------

def test_accent_hex(qapp):
    from utils.toon_customization_resolve import resolve_accent
    assert resolve_accent({"accent": "#56c856"}, QColor("#000")) == QColor("#56c856")


def test_accent_missing_uses_fallback(qapp):
    from utils.toon_customization_resolve import resolve_accent
    assert resolve_accent({}, QColor("#abcabc")) == QColor("#abcabc")


def test_accent_null_uses_fallback(qapp):
    from utils.toon_customization_resolve import resolve_accent
    assert resolve_accent({"accent": None}, QColor("#abcabc")) == QColor("#abcabc")


# -- resolve_body ----------------------------------------------------------

def test_body_hex(qapp):
    from utils.toon_customization_resolve import resolve_body
    assert resolve_body({"body": "#101020"}) == QColor("#101020")


def test_body_missing_returns_none(qapp):
    from utils.toon_customization_resolve import resolve_body
    assert resolve_body({}) is None
    assert resolve_body({"body": None}) is None
