"""Tests for overlay_entry.controller_class(): the env-gated selection between the
single-window ClusterOverlayController (the DEFAULT since the fixed-envelope
transform-scaling rework was live-validated) and the legacy multi-window
OverlayGroupController fallback.

The flag is TTMT_OVERLAY_SINGLE_WINDOW: unset, empty, or any non-falsey value
selects the cluster controller (default); an explicit strtobool falsey token
(``0`` / ``no`` / ``n`` / ``false`` / ``f`` / ``off``, case-insensitive,
surrounding whitespace ignored) opts OUT to the legacy fallback. Importing both
controller classes here is fine - the selection under test only builds the
CLASS object, never the app.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_overlay_entry.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.overlay import overlay_entry
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.group_controller import OverlayGroupController


_ENV = "TTMT_OVERLAY_SINGLE_WINDOW"


def test_default_unset_returns_cluster(monkeypatch):
    """Flag unset -> the single-window cluster controller (the default)."""
    monkeypatch.delenv(_ENV, raising=False)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_selects_cluster(monkeypatch, val):
    """A truthy flag also selects the cluster (the pre-flip opt-in keeps
    working, so existing launch scripts don't flip anyone to legacy)."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize("val", ["", "  "])
def test_empty_value_counts_as_unset_returns_cluster(monkeypatch, val):
    """Empty/whitespace-only counts as UNSET (default = cluster): opting out to
    the legacy fallback requires an explicit falsey token, never an accident."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize(
    "val",
    ["0", "false", "FALSE", "no", "off", "OFF", "n", "f", " off "],
)
def test_falsey_opts_out_to_legacy(monkeypatch, val):
    """The strtobool falsey tokens (0/no/n/false/f/off, any case, whitespace
    ignored) select the legacy multi-window fallback."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is OverlayGroupController
