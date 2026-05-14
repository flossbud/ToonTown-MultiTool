"""Unit tests for utils.x11_discovery — the python-Xlib window discovery
helpers that replaced our xdotool subprocess calls.

These tests mock the Xlib Display so they run in CI / on Windows / over SSH
without a live X server. The goal is to lock the protocol-level expectations
(walking the tree, matching WM_CLASS via substring, reading _NET_WM_PID and
_NET_ACTIVE_WINDOW) so future refactors can't silently break window
detection.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from utils import x11_discovery


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="x11_discovery is Linux-only; helpers no-op on Windows",
)


def _make_window(wid, wm_class=None, children=(), pid=None, x=None):
    """Build a fake Xlib Window object with just the attributes our code
    pokes at. WM_CLASS is a (instance, class) tuple to match python-Xlib."""
    win = MagicMock()
    win.id = wid
    win.get_wm_class.return_value = wm_class
    win.query_tree.return_value = SimpleNamespace(children=list(children))
    # translate_coords result needs an `.x` attribute
    if x is not None:
        win.translate_coords.return_value = SimpleNamespace(x=x, y=0)
    # _NET_WM_PID property: get_full_property returns an object with .value
    if pid is not None:
        win.get_full_property.return_value = SimpleNamespace(value=[pid])
    else:
        win.get_full_property.return_value = None
    return win


def _patched_display(root_window):
    """Build a fake Display whose .screen().root returns the given window
    and whose intern_atom returns an opaque object."""
    d = MagicMock()
    d.screen.return_value = SimpleNamespace(root=root_window)
    d.intern_atom.side_effect = lambda name: f"atom:{name}"
    d.create_resource_object.side_effect = (
        lambda kind, wid: _CREATE_RESOURCE_REGISTRY.get(int(wid))
    )
    return d


# Per-test registry of (wid -> fake window) for create_resource_object.
_CREATE_RESOURCE_REGISTRY: dict[int, MagicMock] = {}


@pytest.fixture(autouse=True)
def _reset_resource_registry():
    _CREATE_RESOURCE_REGISTRY.clear()
    yield
    _CREATE_RESOURCE_REGISTRY.clear()


class TestFindWindowIdsByClass:
    def test_walks_tree_and_returns_matches(self):
        ttr = _make_window(101, wm_class=("ttrengine", "Toontown Rewritten"))
        cc = _make_window(202, wm_class=("corporateclash", "Corporate Clash"))
        firefox = _make_window(303, wm_class=("Navigator", "firefox"))
        root = _make_window(1, children=[ttr, firefox, cc])

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            results = x11_discovery.find_window_ids_by_class(
                ["Toontown Rewritten", "Corporate Clash"]
            )

        assert results == ["101", "202"]

    def test_recurses_into_children(self):
        """X servers commonly nest game windows under wrapper frames; the
        match has to walk past those."""
        ttr = _make_window(101, wm_class=("ttrengine", "Toontown Rewritten"))
        wrapper = _make_window(50, wm_class=None, children=[ttr])
        root = _make_window(1, children=[wrapper])

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            results = x11_discovery.find_window_ids_by_class(["Toontown Rewritten"])

        assert results == ["101"]

    def test_substring_match_matches_xdotool_regex_default(self):
        """xdotool --class uses regex; "Toontown Rewritten" as a regex matches
        the string as a substring. Our substring check is equivalent for the
        two known game classes (no regex specials)."""
        win = _make_window(101, wm_class=("inst", "My Toontown Rewritten Window"))
        root = _make_window(1, children=[win])
        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            results = x11_discovery.find_window_ids_by_class(["Toontown Rewritten"])
        assert results == ["101"]

    def test_empty_class_list_returns_empty(self):
        with patch.object(x11_discovery, "_open_display") as m:
            assert x11_discovery.find_window_ids_by_class([]) == []
            m.assert_not_called()  # short-circuits without opening Display

    def test_no_display_returns_empty(self):
        with patch.object(x11_discovery, "_open_display", return_value=None):
            assert x11_discovery.find_window_ids_by_class(["Toontown Rewritten"]) == []

    def test_window_with_no_wm_class_is_skipped(self):
        no_class = _make_window(10, wm_class=None)
        root = _make_window(1, children=[no_class])
        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            results = x11_discovery.find_window_ids_by_class(["Toontown Rewritten"])
        assert results == []


class TestGetWindowRootX:
    def test_returns_translated_x(self):
        win = _make_window(101, x=1920)
        _CREATE_RESOURCE_REGISTRY[101] = win
        root = _make_window(1)

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_window_root_x("101") == 1920

    def test_returns_none_on_translate_failure(self):
        win = _make_window(101)
        win.translate_coords.side_effect = RuntimeError("BadWindow")
        _CREATE_RESOURCE_REGISTRY[101] = win
        root = _make_window(1)

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_window_root_x("101") is None

    def test_returns_none_without_display(self):
        with patch.object(x11_discovery, "_open_display", return_value=None):
            assert x11_discovery.get_window_root_x("101") is None


class TestGetWindowPid:
    def test_returns_net_wm_pid(self):
        win = _make_window(101, pid=12345)
        _CREATE_RESOURCE_REGISTRY[101] = win
        root = _make_window(1)

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_window_pid("101") == 12345

    def test_returns_none_when_property_missing(self):
        win = _make_window(101)  # pid=None → get_full_property returns None
        _CREATE_RESOURCE_REGISTRY[101] = win
        root = _make_window(1)

        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_window_pid("101") is None


class TestGetActiveWindowId:
    def test_returns_active_window_property(self):
        root = _make_window(1, pid=999)  # reuse pid hook for _NET_ACTIVE_WINDOW value
        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_active_window_id() == "999"

    def test_returns_none_when_no_property(self):
        root = _make_window(1)  # no property set
        with patch.object(x11_discovery, "_open_display",
                          return_value=_patched_display(root)):
            assert x11_discovery.get_active_window_id() is None

    def test_returns_none_without_display(self):
        with patch.object(x11_discovery, "_open_display", return_value=None):
            assert x11_discovery.get_active_window_id() is None
