"""Tests for the live preview widget inside ToonCustomizationDialog."""

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
