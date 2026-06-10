"""Geometry/toplevel helpers with a faked _open_display."""
from types import SimpleNamespace

from utils import x11_discovery


class _FakeGeo:
    width, height = 800, 600


class _FakeCoords:
    x, y = 120, 80
    child = SimpleNamespace(id=0xAB)


class _FakeWin:
    id = 0x77

    def translate_coords(self, src, x, y):
        return _FakeCoords()

    def get_geometry(self):
        return _FakeGeo()

    def query_tree(self):
        return SimpleNamespace(parent=SimpleNamespace(id=0x1, query_tree=None))


class _FakeRoot(_FakeWin):
    id = 0x1


class _FakeDisplay:
    def screen(self):
        return SimpleNamespace(root=_FakeRoot())

    def create_resource_object(self, kind, wid):
        return _FakeWin()


def test_get_window_geometry(monkeypatch):
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: _FakeDisplay())
    assert x11_discovery.get_window_geometry("119") == (120, 80, 800, 600)


def test_get_window_geometry_no_display(monkeypatch):
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: None)
    assert x11_discovery.get_window_geometry("119") is None


def test_toplevel_at_point(monkeypatch):
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: _FakeDisplay())
    assert x11_discovery.toplevel_at_point(200, 300) == str(0xAB)


def test_toplevel_ancestor_direct_child_of_root(monkeypatch):
    # _FakeWin's parent IS root (0x1), so the toplevel ancestor is the window itself.
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: _FakeDisplay())
    assert x11_discovery.toplevel_ancestor(str(0x77)) == str(0x77)
