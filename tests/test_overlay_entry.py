"""Tests for overlay_entry.controller_class(): the env-gated selection between the
legacy multi-window OverlayGroupController (the shipped default) and the opt-in
single-window ClusterOverlayController.

The flag is TTMT_OVERLAY_SINGLE_WINDOW: truthy (a non-empty value that is NOT a
strtobool falsey token - ``0`` / ``no`` / ``n`` / ``false`` / ``f`` / ``off``,
case-insensitive, surrounding whitespace ignored) selects the cluster controller;
unset / empty / a falsey token keeps the legacy controller. Importing both controller classes here is fine - the selection under
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


def test_default_unset_returns_legacy(monkeypatch):
    """Flag unset -> the legacy multi-window controller (unchanged behavior)."""
    monkeypatch.delenv(_ENV, raising=False)
    assert overlay_entry.controller_class() is OverlayGroupController


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_selects_cluster(monkeypatch, val):
    """A truthy flag opts into the single-window cluster controller."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is ClusterOverlayController


@pytest.mark.parametrize(
    "val",
    ["0", "", "false", "FALSE", "no", "  ", "off", "OFF", "n", "f", " off "],
)
def test_falsey_returns_legacy(monkeypatch, val):
    """The strtobool falsey tokens (0/no/n/false/f/off, any case, whitespace
    ignored) plus empty/whitespace-only stay on the legacy controller - so a user
    who writes ``=off`` to disable the flag isn't surprised by it turning on."""
    monkeypatch.setenv(_ENV, val)
    assert overlay_entry.controller_class() is OverlayGroupController
