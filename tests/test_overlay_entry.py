"""Tests for overlay_entry.controller_class(): the env-gated selection between the
single-window ClusterOverlayController (now the DEFAULT) and the legacy
multi-window OverlayGroupController (explicit opt-OUT).

The flag is TTMT_OVERLAY_SINGLE_WINDOW. The single-window cluster is the default:
unset, empty/whitespace-only, or any truthy value selects it. Only an EXPLICIT
strtobool falsey token - ``0`` / ``no`` / ``n`` / ``false`` / ``f`` / ``off``
(case-insensitive, surrounding whitespace ignored) - falls back to the legacy
controller. Importing both controller classes here is fine - the selection under
test only builds the CLASS object, never the app.

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
    """Flag unset -> the single-window cluster controller (the new default), so a
    plain ``python main.py`` gets the single-window overlay."""
    monkeypatch.delenv(_ENV, raising=False)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "", "  "])
def test_default_on_selects_cluster(monkeypatch, val):
    """Any truthy value - AND present-but-empty/whitespace-only - selects the
    single-window cluster (default on; only an explicit falsey token opts out)."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize(
    "val",
    ["0", "false", "FALSE", "no", "off", "OFF", "n", "f", " off "],
)
def test_explicit_falsey_opts_out_to_legacy(monkeypatch, val):
    """An EXPLICIT strtobool falsey token (0/no/n/false/f/off, any case, whitespace
    ignored) opts OUT to the legacy multi-window controller - the fall-back if the
    single-window path misbehaves."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is OverlayGroupController
