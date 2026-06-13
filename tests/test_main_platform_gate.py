"""Locks the QT_QPA_PLATFORM decision: Linux must default to xcb (or wayland with
the opt-in), and darwin/win32 must return None so Qt picks its native plugin
(cocoa / windows). Guards against regressing macOS back into the X11 xcb plugin,
which does not exist on macOS and would crash at startup."""
from utils.platform_qt import qt_platform_for


def test_qt_platform_for():
    assert qt_platform_for("linux", session="x11", force_wayland=False) == "xcb"
    assert qt_platform_for("linux", session="wayland", force_wayland=True) == "wayland"
    assert qt_platform_for("linux", session="wayland", force_wayland=False) == "xcb"
    # darwin and win32 must NOT be forced to xcb (None => leave Qt default).
    assert qt_platform_for("darwin", session="", force_wayland=False) is None
    assert qt_platform_for("win32", session="", force_wayland=False) is None
