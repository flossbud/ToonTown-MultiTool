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


# -- resolve_pose ----------------------------------------------------------

def test_resolve_pose_known(qapp):
    from utils.toon_customization_resolve import resolve_pose
    assert resolve_pose({"pose": "portrait-grin"}) == "portrait-grin"


def test_resolve_pose_unknown_falls_back(qapp):
    from utils.toon_customization_resolve import resolve_pose
    assert resolve_pose({"pose": "not-a-real-pose"}) == "portrait"


def test_resolve_pose_missing_falls_back(qapp):
    from utils.toon_customization_resolve import resolve_pose
    assert resolve_pose({}) == "portrait"
    assert resolve_pose({"pose": None}) == "portrait"


def test_resolve_pose_custom_fallback(qapp):
    from utils.toon_customization_resolve import resolve_pose
    assert resolve_pose({"pose": None}, fallback="head") == "head"


# -- resolve_portrait_transform --------------------------------------------

def test_resolve_portrait_transform_default(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    assert resolve_portrait_transform({}) == (1.0, 0.0, 0.0, 0.0)


def test_resolve_portrait_transform_round_trip(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    entry = {
        "portrait": {
            "transform": {
                "zoom": 1.4,
                "offset_x": 0.25,
                "offset_y": -0.1,
                "rotate": 30.0,
            }
        }
    }
    assert resolve_portrait_transform(entry) == (1.4, 0.25, -0.1, 30.0)


def test_resolve_portrait_transform_clamps_zoom(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    high = {"portrait": {"transform": {"zoom": 10.0}}}
    low = {"portrait": {"transform": {"zoom": 0.1}}}
    assert resolve_portrait_transform(high)[0] == 3.0
    assert resolve_portrait_transform(low)[0] == 0.5


def test_resolve_portrait_transform_clamps_offsets(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    big = {"portrait": {"transform": {"offset_x": 5.0, "offset_y": -3.0}}}
    z, ox, oy, r = resolve_portrait_transform(big)
    assert ox == 1.0
    assert oy == -1.0


def test_resolve_portrait_transform_normalizes_rotate(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    e = {"portrait": {"transform": {"rotate": 270.0}}}
    z, ox, oy, r = resolve_portrait_transform(e)
    # 270 normalized into [-180, 180] is -90.
    assert r == -90.0


def test_resolve_portrait_transform_non_dict_falls_back(qapp):
    from utils.toon_customization_resolve import resolve_portrait_transform
    assert resolve_portrait_transform(None) == (1.0, 0.0, 0.0, 0.0)
    assert resolve_portrait_transform({"portrait": "garbage"}) == (1.0, 0.0, 0.0, 0.0)
    assert resolve_portrait_transform({"portrait": {"transform": "garbage"}}) == (1.0, 0.0, 0.0, 0.0)


# -- resolve_circle_outline ------------------------------------------------

@pytest.mark.parametrize("preset,px", [("thin", 1), ("medium", 2), ("thick", 4)])
def test_resolve_circle_outline_returns_color_and_width_per_preset(qapp, preset, px):
    from utils.toon_customization_resolve import resolve_circle_outline
    entry = {"portrait": {"outline": {"color": "#ffd84a", "width": preset}}}
    result = resolve_circle_outline(entry)
    assert result is not None
    color, width = result
    assert color.name() == "#ffd84a"
    assert width == px


def test_resolve_circle_outline_returns_none_when_missing(qapp):
    from utils.toon_customization_resolve import resolve_circle_outline
    assert resolve_circle_outline({}) is None
    assert resolve_circle_outline({"portrait": {}}) is None


def test_resolve_circle_outline_returns_none_when_color_invalid(qapp):
    from utils.toon_customization_resolve import resolve_circle_outline
    entry = {"portrait": {"outline": {"color": "not-a-hex", "width": "medium"}}}
    assert resolve_circle_outline(entry) is None


def test_resolve_circle_outline_falls_back_to_medium_for_unknown_width(qapp):
    from utils.toon_customization_resolve import resolve_circle_outline
    entry = {"portrait": {"outline": {"color": "#ffffff", "width": "huge"}}}
    color, width = resolve_circle_outline(entry)
    assert color.name() == "#ffffff"
    assert width == 2
