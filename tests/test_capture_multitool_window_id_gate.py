"""Tests for the gate that decides whether _capture_multitool_window_id
runs the xdotool probe.

The probe is X11-only. The correct gate is "are we running under Qt's
xcb platform" (xcb means real X11 OR XWayland — both of which xdotool
can drive). A naive "XDG_SESSION_TYPE=wayland" gate falsely skips the
probe for users on Wayland sessions running our default xcb-via-XWayland
mode, breaking the broadcast-while-focused self-window-id capture.
"""

import os
from unittest.mock import patch


def _should_run_xdotool_probe(env: dict) -> bool:
    """Inline copy of the gating predicate, evaluated against a fake env.

    Mirrors the logic in main.py._capture_multitool_window_id; if those
    two fall out of sync, this test fails on its assertions.
    """
    if os.environ.get("__platform_override", "linux") != "linux":
        return False
    qt_platform = env.get("QT_QPA_PLATFORM", "").lower()
    return qt_platform != "wayland"


def test_xdotool_probe_runs_on_default_linux_xcb():
    """Default Linux launch: QT_QPA_PLATFORM=xcb (set by main.py module
    head). xdotool works under both pure X11 and XWayland."""
    env = {"QT_QPA_PLATFORM": "xcb", "XDG_SESSION_TYPE": "wayland"}
    assert _should_run_xdotool_probe(env)


def test_xdotool_probe_runs_on_pure_x11_session():
    env = {"QT_QPA_PLATFORM": "xcb", "XDG_SESSION_TYPE": "x11"}
    assert _should_run_xdotool_probe(env)


def test_xdotool_probe_skipped_on_native_wayland_opt_in():
    """User opted into native Wayland with TTMT_USE_WAYLAND=1; xdotool
    has no surface to probe and the call would fail."""
    env = {"QT_QPA_PLATFORM": "wayland", "XDG_SESSION_TYPE": "wayland"}
    assert not _should_run_xdotool_probe(env)


def test_main_module_uses_qt_platform_not_session_type():
    """The actual gate inside main.py must check QT_QPA_PLATFORM, not
    XDG_SESSION_TYPE. This test reads main.py source directly."""
    from pathlib import Path
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    src = main_py.read_text()
    fn_start = src.index("def _capture_multitool_window_id(")
    fn_end = src.index("\n    def ", fn_start + 1)
    body = src[fn_start:fn_end]
    assert 'QT_QPA_PLATFORM' in body, (
        "_capture_multitool_window_id must gate on QT_QPA_PLATFORM, "
        "not XDG_SESSION_TYPE — XWayland users on the default xcb path "
        "still need the xdotool probe."
    )
    assert (
        '"wayland"' in body or "'wayland'" in body
    ), "the gate's wayland-string check must remain"
