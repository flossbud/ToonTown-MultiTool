"""Overlay controller selection: single-window cluster by DEFAULT.

``controller_class()`` returns the overlay controller CLASS the app should
construct. The single-window ``ClusterOverlayController`` is the default (it
scales as one fixed-envelope transform - judder-free by construction, live-
validated 2026-07-01); the legacy multi-window ``OverlayGroupController``
remains reachable as a fallback by setting ``TTMT_OVERLAY_SINGLE_WINDOW`` to a
falsey token (``0`` / ``no`` / ``off`` / ...).

The two controllers share the same constructor signature and caller surface, so
the selection here is a pure drop-in swap; the caller instantiates whichever
class this returns.
"""
from __future__ import annotations

import os

# Env var that selects the overlay path. Unset or truthy -> the single-window
# cluster (default); a falsey token -> the legacy multi-window fallback.
_ENV_FLAG = "TTMT_OVERLAY_SINGLE_WINDOW"

# Values (case-insensitive, surrounding whitespace ignored) that select the
# LEGACY fallback. Matches the widely-understood strtobool false tokens so a
# user who writes ``=off`` / ``=no`` / ``=f`` gets the legacy path as expected.
# NOTE: unlike the opt-in era, an EMPTY/whitespace-only value now counts as
# unset (default = cluster); only an explicit falsey token opts out.
_FALSEY = {"0", "no", "n", "false", "f", "off"}


def _single_window_enabled() -> bool:
    """True (the default) unless ``TTMT_OVERLAY_SINGLE_WINDOW`` opts OUT.

    Unset, empty/whitespace-only, or any non-falsey value -> the single-window
    cluster. Only an explicit strtobool falsey token ``0`` / ``no`` / ``n`` /
    ``false`` / ``f`` / ``off`` (case-insensitive, surrounding whitespace
    ignored) selects the legacy multi-window fallback.
    """
    raw = os.environ.get(_ENV_FLAG)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSEY


def controller_class():
    """Return the overlay controller CLASS to construct (the caller instantiates
    it). The single-window ``ClusterOverlayController`` by default; the legacy
    ``OverlayGroupController`` when ``TTMT_OVERLAY_SINGLE_WINDOW`` is set to a
    falsey token.

    The chosen class is LAZY-imported inside this function so importing this
    module never drags in either controller (avoiding import cost + potential
    import cycles at module load); only the selected one is imported.
    """
    if _single_window_enabled():
        from utils.overlay.cluster_controller import ClusterOverlayController
        return ClusterOverlayController
    from utils.overlay.group_controller import OverlayGroupController
    return OverlayGroupController
