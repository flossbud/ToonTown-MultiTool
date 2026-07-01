"""Overlay controller selection behind an OFF-by-default env flag.

``controller_class()`` returns the overlay controller CLASS the app should
construct. The single-window ``ClusterOverlayController`` is opt-in via the
``TTMT_OVERLAY_SINGLE_WINDOW`` environment variable; with the flag unset (or set
to a falsey value) the legacy multi-window ``OverlayGroupController`` - the
shipped default - is returned, so behavior is unchanged unless the user opts in.

The two controllers share the same constructor signature and caller surface, so
the selection here is a pure drop-in swap; the caller instantiates whichever
class this returns.
"""
from __future__ import annotations

import os

# Env var that opts INTO the single-window cluster overlay.
_ENV_FLAG = "TTMT_OVERLAY_SINGLE_WINDOW"

# Values (case-insensitive, surrounding whitespace ignored) that count as OFF
# even when the variable is present. An empty/whitespace-only value is OFF too.
_FALSEY = {"", "0", "false", "no"}


def _single_window_enabled() -> bool:
    """True when ``TTMT_OVERLAY_SINGLE_WINDOW`` opts into the single-window cluster.

    Truthy = the variable is set to a non-empty value that is NOT one of
    ``0`` / ``false`` / ``no`` (case-insensitive, surrounding whitespace ignored).
    Everything else - unset, empty/whitespace-only, or one of those falsey tokens
    - is OFF and keeps the legacy controller.
    """
    raw = os.environ.get(_ENV_FLAG)
    if raw is None:
        return False
    return raw.strip().lower() not in _FALSEY


def controller_class():
    """Return the overlay controller CLASS to construct (the caller instantiates
    it). The single-window ``ClusterOverlayController`` when
    ``TTMT_OVERLAY_SINGLE_WINDOW`` is truthy; otherwise the legacy
    ``OverlayGroupController`` (the default).

    The chosen class is LAZY-imported inside this function so importing this
    module never drags in either controller (avoiding import cost + potential
    import cycles at module load); only the selected one is imported.
    """
    if _single_window_enabled():
        from utils.overlay.cluster_controller import ClusterOverlayController
        return ClusterOverlayController
    from utils.overlay.group_controller import OverlayGroupController
    return OverlayGroupController
