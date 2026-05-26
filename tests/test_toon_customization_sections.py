"""Smoke test: section widgets are importable from the extracted module."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_section_module_exports_widgets(qapp):
    from utils.widgets.toon_customization_sections import (
        PRESET_SWATCHES,
        _SwatchRow,
        _SimpleColorSection,
        _ChipRow,
        _PoseTile,
        _PoseAdjustPreview,
        _PoseAdjustView,
        _PoseSection,
        _PortraitSection,
    )
    assert isinstance(PRESET_SWATCHES, tuple)
    assert _SwatchRow is not None
    assert _SimpleColorSection is not None
    assert _ChipRow is not None
    assert _PoseTile is not None
    assert _PoseAdjustPreview is not None
    assert _PoseAdjustView is not None
    assert _PoseSection is not None
    assert _PortraitSection is not None


