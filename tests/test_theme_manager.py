"""Tests for utils.theme_manager typography helpers."""

import os
import time
from unittest.mock import patch

import pytest

from utils.theme_manager import font_role, TYPOGRAPHY, LIGHT_THEME, should_set_xdg_portal_platformtheme
from utils import theme_manager


@pytest.fixture(autouse=True)
def _reset_color_scheme_cache():
    """Drop the system-color-scheme cache around every test in this module
    so cache state from one test never leaks into another."""
    theme_manager.invalidate_system_color_scheme_cache()
    yield
    theme_manager.invalidate_system_color_scheme_cache()


def test_font_role_known_roles_return_ints():
    for role in ("display", "title", "body", "label", "caption"):
        size = font_role(role)
        assert isinstance(size, int)
        assert 8 <= size <= 32, f"role={role} size={size} out of plausible range"


def test_font_role_scale_is_monotonic():
    # display > title > body > label > caption
    sizes = [font_role(r) for r in ("display", "title", "body", "label", "caption")]
    assert sizes == sorted(sizes, reverse=True), f"non-monotonic scale: {sizes}"


def test_font_role_unknown_falls_back_to_body():
    assert font_role("nonexistent") == font_role("body")


def test_typography_dict_has_canonical_roles():
    assert {"display", "title", "body", "label", "caption"} <= set(TYPOGRAPHY.keys())


def test_light_theme_uses_gradient_background():
    """The flat #f0f0f0 background was replaced with a subtle gradient."""
    assert "qlineargradient" in LIGHT_THEME, (
        "LIGHT_THEME should use qlineargradient for app background depth"
    )


def test_should_set_xdg_portal_returns_false_when_already_set():
    with patch.dict(os.environ, {"QT_QPA_PLATFORMTHEME": "kde", "XDG_CURRENT_DESKTOP": "GNOME"}):
        assert should_set_xdg_portal_platformtheme(plugin_path=__file__) is False


def test_should_set_xdg_portal_returns_false_when_plugin_missing():
    with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False):
        os.environ.pop("QT_QPA_PLATFORMTHEME", None)
        assert should_set_xdg_portal_platformtheme(plugin_path="/does/not/exist") is False


def test_should_set_xdg_portal_returns_true_on_gnome_with_plugin():
    with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False):
        os.environ.pop("QT_QPA_PLATFORMTHEME", None)
        assert should_set_xdg_portal_platformtheme(plugin_path=__file__) is True


def test_should_set_xdg_portal_returns_true_on_gnome_likes():
    for desktop in ("ubuntu:GNOME", "Unity", "Pantheon", "Budgie:GNOME"):
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": desktop}, clear=False):
            os.environ.pop("QT_QPA_PLATFORMTHEME", None)
            assert should_set_xdg_portal_platformtheme(plugin_path=__file__) is True, \
                f"expected True for XDG_CURRENT_DESKTOP={desktop!r}"


def test_should_set_xdg_portal_returns_false_on_non_gnome_desktops():
    # X-Cinnamon is treated as non-GNOME-like: Cinnamon's appearance setting
    # is org.cinnamon.desktop.interface.gtk-theme, not the freedesktop
    # appearance portal, so the portal plugin would not give live updates
    # there even if loaded.
    for desktop in ("KDE", "XFCE", "MATE", "LXQt", "sway", "X-Cinnamon", ""):
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": desktop}, clear=False):
            os.environ.pop("QT_QPA_PLATFORMTHEME", None)
            assert should_set_xdg_portal_platformtheme(plugin_path=__file__) is False, \
                f"expected False for XDG_CURRENT_DESKTOP={desktop!r}"


def test_detect_system_color_scheme_caches_within_ttl():
    """Repeated calls within the TTL should not re-resolve."""
    call_count = {"n": 0}

    def fake_qt():
        call_count["n"] += 1
        return "dark"

    with patch.object(theme_manager, "_color_scheme_from_qt", side_effect=fake_qt):
        first = theme_manager.detect_system_color_scheme()
        second = theme_manager.detect_system_color_scheme()
        third = theme_manager.detect_system_color_scheme()

    assert first == second == third == "dark"
    assert call_count["n"] == 1, f"expected single resolution, got {call_count['n']}"


def test_detect_system_color_scheme_invalidate_forces_reresolve():
    """Calling invalidate_system_color_scheme_cache() between two
    detect_system_color_scheme() calls forces the second to re-resolve."""
    call_count = {"n": 0}

    def fake_qt():
        call_count["n"] += 1
        return "light"

    with patch.object(theme_manager, "_color_scheme_from_qt", side_effect=fake_qt):
        theme_manager.detect_system_color_scheme()
        theme_manager.invalidate_system_color_scheme_cache()
        theme_manager.detect_system_color_scheme()

    assert call_count["n"] == 2, f"invalidation should force re-resolution, got {call_count['n']}"


def test_detect_system_color_scheme_cache_expires_after_ttl():
    """After more than _SYSTEM_COLOR_SCHEME_CACHE_TTL seconds elapse since
    the last cache write, the next call re-resolves the OS color scheme."""
    call_count = {"n": 0}

    def fake_qt():
        call_count["n"] += 1
        return "dark"

    # Patch the TTL very low so the test runs fast.
    with patch.object(theme_manager, "_SYSTEM_COLOR_SCHEME_CACHE_TTL", 0.05), \
         patch.object(theme_manager, "_color_scheme_from_qt", side_effect=fake_qt):
        theme_manager.detect_system_color_scheme()
        time.sleep(0.1)  # 2x the patched TTL (0.05s); wide enough for scheduler jitter
        theme_manager.detect_system_color_scheme()

    assert call_count["n"] == 2, f"expected re-resolve after TTL, got {call_count['n']}"
