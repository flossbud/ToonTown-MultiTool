"""Tests for the live preview widget used by the customization overlay."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_construct_with_empty_draft(qapp):
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(game="ttr", toon_name="Flossbud", draft={})
    assert w.draft() == {}


def test_set_draft_triggers_repaint_request(qapp):
    """Setting the draft must call update() so the next paint reflects it."""
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(game="ttr", toon_name="Flossbud", draft={})
    w.set_draft({"accent": "#56c856"})
    assert w.draft() == {"accent": "#56c856"}


def test_fixed_size_in_range(qapp):
    """The preview occupies a fixed footprint suitable for the dialog."""
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(game="ttr", toon_name="Flossbud", draft={})
    assert w.minimumWidth() >= 320
    assert w.minimumHeight() >= 60


def test_paint_does_not_crash_with_full_draft(qapp):
    """All resolver paths exercised; the widget must not raise."""
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(
        game="ttr",
        toon_name="Flossbud",
        draft={
            "portrait": {
                "color": "#d9a04e",
                "gradient": {"start": "#ff0000", "end": "#00ff00"},
                "pattern": {"name": "dots", "color": "#ffffff"},
            },
            "accent": "#56c856",
            "body": "#101020",
        },
    )
    w.resize(360, 72)
    w.show()
    qapp.processEvents()
    w.hide()


def test_preview_constructs_with_dna(qapp):
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(
        game="ttr", toon_name="Flossbud", draft={}, dna="dna-test-123",
    )
    assert w.dna() == "dna-test-123"


def test_preview_set_draft_with_pose_requests_pixmap(qapp, monkeypatch):
    """Setting a draft with a pose should ask the fetcher for that pose."""
    requested = []

    from utils.rendition_poses import RenditionPoseFetcher
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )

    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(
        game="ttr", toon_name="Flossbud", draft={}, dna="dna-test-123",
    )
    requested.clear()  # ignore constructor-time request
    w.set_draft({"pose": "portrait-grin"})
    assert ("dna-test-123", "portrait-grin") in requested


def test_preview_without_dna_does_not_request(qapp, monkeypatch):
    requested = []
    from utils.rendition_poses import RenditionPoseFetcher
    monkeypatch.setattr(
        RenditionPoseFetcher,
        "request",
        lambda self, dna, pose: requested.append((dna, pose)),
    )
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(
        game="ttr", toon_name="Flossbud", draft={"pose": "portrait-grin"}, dna=None,
    )
    assert requested == []


def test_preview_current_portrait_transform(qapp):
    """Test hook: preview exposes the current transform that paintEvent
    will apply to the pose pixmap."""
    from utils.widgets.card_preview_widget import CardPreviewWidget
    w = CardPreviewWidget(
        game="ttr", toon_name="Flossbud", draft={}, dna="dna-test-123",
    )
    assert w.current_portrait_transform() == (1.0, 0.0, 0.0, 0.0)

    w.set_draft({
        "portrait": {
            "transform": {
                "zoom": 1.25,
                "offset_x": 0.1,
                "offset_y": 0.2,
                "rotate": -15.0,
            }
        }
    })
    assert w.current_portrait_transform() == (1.25, 0.1, 0.2, -15.0)


def test_card_preview_draws_circle_outline_when_set(qapp):
    """Painting with a circle outline set should produce a pixel ring
    matching the outline color around the portrait circle's perimeter."""
    from utils.widgets.card_preview_widget import CardPreviewWidget

    draft = {"portrait": {
        "color": "#000000",
        "outline": {"color": "#ffd84a", "width": "thick"},
    }}
    w = CardPreviewWidget("ttr", "Test", draft)
    w.resize(360, 72)
    pm = w.grab()
    img = pm.toImage()
    # Portrait circle is at (10..50, 16..56) (40px diameter, centered
    # vertically in 72px tall card with +1 offset).
    # Sample a pixel right on the circle's left edge: (10, 36)
    px = img.pixelColor(10, 36)
    assert px.alpha() > 0
    # Outline color is #ffd84a (very yellow). Tolerate AA.
    assert px.red() > 200 and px.green() > 180 and px.blue() < 120


def test_card_preview_invokes_silhouette_builders_when_set(qapp, monkeypatch):
    """When silhouette outline or shadow is set, the paint pipeline
    calls the effect builders. Verified via monkeypatch spies."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.widgets.card_preview_widget import CardPreviewWidget
    import utils.portrait_effects as eff

    outline_calls = []
    shadow_calls = []

    def fake_outline(pose, color, width):
        outline_calls.append((color.name(), width))
        out = QPixmap(pose.size())
        out.fill(Qt.transparent)
        return out

    def fake_shadow(pose, color, blur):
        shadow_calls.append((color.name(), blur))
        out = QPixmap(pose.width() + 2 * blur, pose.height() + 2 * blur)
        out.fill(Qt.transparent)
        return out

    monkeypatch.setattr(eff, "build_silhouette_outline_pixmap", fake_outline)
    monkeypatch.setattr(eff, "build_silhouette_shadow_pixmap", fake_shadow)

    draft = {"portrait": {
        "silhouette": {
            "outline": {"color": "#ffd84a", "width": "medium"},
            "shadow": {"color": "#000000", "softness": "medium"},
        },
    }}
    w = CardPreviewWidget("ttr", "Test", draft, dna="dna-1")
    # Inject a fake source pose pixmap so the cache key is stable.
    fake = QPixmap(40, 40)
    fake.fill(Qt.red)
    w._pose_pixmap = fake
    w.show()
    w.repaint()
    qapp.processEvents()
    assert outline_calls == [("#ffd84a", 2)]
    assert shadow_calls == [("#000000", 12)]


def test_card_preview_silhouette_cache_returns_same_pixmap(qapp, monkeypatch):
    """Repainting without changing the draft should not re-invoke the
    effect builders."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.widgets.card_preview_widget import CardPreviewWidget
    import utils.portrait_effects as eff

    calls = []
    monkeypatch.setattr(
        eff, "build_silhouette_outline_pixmap",
        lambda pm, c, w: (calls.append("out"), QPixmap(pm.size()))[1],
    )
    monkeypatch.setattr(
        eff, "build_silhouette_shadow_pixmap",
        lambda pm, c, b: (calls.append("shd"),
                          QPixmap(pm.width() + 2 * b, pm.height() + 2 * b))[1],
    )

    draft = {"portrait": {"silhouette": {
        "outline": {"color": "#fff", "width": "medium"},
        "shadow":  {"color": "#000", "softness": "medium"},
    }}}
    w = CardPreviewWidget("ttr", "Test", draft, dna="dna-1")
    fake = QPixmap(40, 40); fake.fill(Qt.red)
    w._pose_pixmap = fake
    w.show()
    w.repaint(); qapp.processEvents()
    initial = len(calls)
    assert initial == 2
    w.repaint(); qapp.processEvents()
    assert len(calls) == initial  # cached, no new calls


def test_card_preview_silhouette_cache_invalidated_when_pose_changes(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.widgets.card_preview_widget import CardPreviewWidget
    import utils.portrait_effects as eff
    calls = []
    monkeypatch.setattr(
        eff, "build_silhouette_outline_pixmap",
        lambda pm, c, w: (calls.append("out"), QPixmap(pm.size()))[1],
    )
    monkeypatch.setattr(
        eff, "build_silhouette_shadow_pixmap",
        lambda pm, c, b: (calls.append("shd"),
                          QPixmap(pm.width() + 2 * b, pm.height() + 2 * b))[1],
    )

    draft = {"portrait": {"silhouette": {
        "outline": {"color": "#fff", "width": "medium"},
    }}}
    w = CardPreviewWidget("ttr", "Test", draft, dna="dna-1")
    pm1 = QPixmap(40, 40); pm1.fill(Qt.red)
    w._pose_pixmap = pm1
    w.show()
    w.repaint(); qapp.processEvents()
    assert calls == ["out"]
    pm2 = QPixmap(40, 40); pm2.fill(Qt.blue)
    w._pose_pixmap = pm2
    w.repaint(); qapp.processEvents()
    # Pose changed → cache key (id(pose_pm)) differs → builder invoked again.
    assert calls == ["out", "out"]
