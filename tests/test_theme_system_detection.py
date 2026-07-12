"""System-theme detection: portal no-preference mapping + self-palette loop.

Regression tests for the 2026-07-12 live finding: on GNOME light mode the
portal reports appearance value 0 ('default' = no preference), both real
detectors return None, and the last-resort heuristic read the app's OWN
palette - so after one manual Dark, "System" resolved to dark forever.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest

from utils import theme_manager as tm


def test_portal_value_mapping_no_preference_is_light():
    # Per org.freedesktop.appearance: 0 = no preference, 1 = dark, 2 = light.
    # GNOME reports 0 for its 'default' (light) appearance, so 0 must read
    # as light - never as "unknown" (which used to fall through to the
    # self-palette heuristic).
    assert tm._portal_value_to_scheme(1) == "dark"
    assert tm._portal_value_to_scheme(2) == "light"
    assert tm._portal_value_to_scheme(0) == "light"
    assert tm._portal_value_to_scheme(7) is None


def test_system_detection_immune_to_self_applied_dark(qapp, monkeypatch):
    # Simulate the from-source GNOME-light stack: no Qt platform theme
    # answer, no portal answer. Detection may then only ever consult the
    # app palette while the app has NOT overridden it.
    monkeypatch.setattr(tm, "_color_scheme_from_qt", lambda: None)
    monkeypatch.setattr(tm, "_color_scheme_from_portal", lambda timeout=1.0: None)

    tm.apply_theme(qapp, "light")       # known-light palette (shared qapp may be dark)
    tm.invalidate_system_color_scheme_cache()
    monkeypatch.setattr(tm, "_APPLIED_THEME", None)   # ...but flagged pristine
    monkeypatch.setattr(tm, "_OS_SCHEME_LAST_HONEST", None)
    pristine = tm.detect_system_color_scheme()
    assert pristine == "light"          # pristine palette, no theme applied yet

    tm.apply_theme(qapp, "dark")        # user flips the app to Dark
    try:
        tm.invalidate_system_color_scheme_cache()
        # The poisoned path returned "dark" here (reading our own palette).
        assert tm.detect_system_color_scheme() == "light"
    finally:
        tm.apply_theme(qapp, "light")   # restore for other tests
        tm.invalidate_system_color_scheme_cache()


def test_honest_detector_answer_is_remembered_for_fallback(qapp, monkeypatch):
    # A real (portal) answer must be remembered, so if the portal later goes
    # quiet while the app palette is self-owned, "system" holds the last
    # honest OS value instead of echoing the app.
    monkeypatch.setattr(tm, "_color_scheme_from_qt", lambda: None)
    monkeypatch.setattr(tm, "_OS_SCHEME_LAST_HONEST", None)
    monkeypatch.setattr(tm, "_color_scheme_from_portal", lambda timeout=1.0: "dark")
    tm.invalidate_system_color_scheme_cache()
    assert tm.detect_system_color_scheme() == "dark"

    monkeypatch.setattr(tm, "_color_scheme_from_portal", lambda timeout=1.0: None)
    tm.apply_theme(qapp, "light")       # app palette now light, self-owned
    try:
        tm.invalidate_system_color_scheme_cache()
        assert tm.detect_system_color_scheme() == "dark"   # remembered, not echoed
    finally:
        tm.invalidate_system_color_scheme_cache()
