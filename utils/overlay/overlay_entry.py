"""Overlay controller selection: the single-window cluster is the DEFAULT.

``controller_class()`` returns the overlay controller CLASS the app should
construct. The single-window ``ClusterOverlayController`` is used by default; the
legacy multi-window ``OverlayGroupController`` is an explicit opt-OUT, selected
only when ``TTMT_OVERLAY_SINGLE_WINDOW`` is set to a falsey value
(``0`` / ``no`` / ``n`` / ``false`` / ``f`` / ``off``). Unset, empty, or any
truthy value selects the single-window cluster.

The two controllers share the same constructor signature and caller surface, so
the selection here is a pure drop-in swap; the caller instantiates whichever
class this returns.
"""
from __future__ import annotations

import os

# Env var that opts OUT of the (now default) single-window cluster overlay.
_ENV_FLAG = "TTMT_OVERLAY_SINGLE_WINDOW"

# Explicit falsey tokens (case-insensitive, surrounding whitespace ignored) that
# opt OUT to the legacy multi-window controller. Matches the widely-understood
# strtobool false set. NOTE: "" is deliberately NOT here - an unset OR empty value
# keeps the single-window default; only an explicit ``0``/``off``/``no``/... opts out.
_FALSEY = {"0", "no", "n", "false", "f", "off"}


def _single_window_enabled() -> bool:
    """True when the single-window cluster should be used - which is the DEFAULT.

    Returns True unless the variable is set to an explicit strtobool falsey token
    ``0`` / ``no`` / ``n`` / ``false`` / ``f`` / ``off`` (case-insensitive,
    surrounding whitespace ignored). Unset, empty, whitespace-only, or any truthy
    value all select the single-window cluster; only an explicit falsey token opts
    out to the legacy multi-window controller.
    """
    raw = os.environ.get(_ENV_FLAG)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSEY


def controller_class():
    """Return the overlay controller CLASS to construct (the caller instantiates
    it). The single-window ``ClusterOverlayController`` by default; the legacy
    ``OverlayGroupController`` only when ``TTMT_OVERLAY_SINGLE_WINDOW`` is set to a
    falsey value.

    The chosen class is LAZY-imported inside this function so importing this
    module never drags in either controller (avoiding import cost + potential
    import cycles at module load); only the selected one is imported.
    """
    if _single_window_enabled():
        from utils.overlay.cluster_controller import ClusterOverlayController
        return ClusterOverlayController
    from utils.overlay.group_controller import OverlayGroupController
    return OverlayGroupController
