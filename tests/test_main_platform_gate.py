import importlib
m = importlib.import_module("utils.platform_qt")


def test_qt_platform_for():
    assert m.qt_platform_for("linux", session="x11", force_wayland=False) == "xcb"
    assert m.qt_platform_for("linux", session="wayland", force_wayland=True) == "wayland"
    assert m.qt_platform_for("linux", session="wayland", force_wayland=False) == "xcb"
    # darwin and win32 must NOT be forced to xcb (None => leave Qt default).
    assert m.qt_platform_for("darwin", session="", force_wayland=False) is None
    assert m.qt_platform_for("win32", session="", force_wayland=False) is None
