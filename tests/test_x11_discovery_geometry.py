"""Geometry/toplevel helpers with a faked _open_display.

The fakes model translate_coords arg DIRECTION and real offsets, not
constants: this file must be able to catch the historical swapped-args
negation bug (see tests/test_x11_discovery_root_x.py), python-xlib's
raw-int-0 X.NONE replies (child over root, parent of root), and the
multi-hop ancestor walk under a reparenting WM.
"""
from types import SimpleNamespace

from utils import x11_discovery


class _FakeWindow:
    """Window in a tiny fake hierarchy with ABSOLUTE root-space origins.
    dst.translate_coords(src, x, y) models the real direction semantics:
    returns src_origin - dst_origin + (x, y), plus the topmost child of
    dst containing the point (raw int 0 when none, like python-xlib's
    X.NONE parse)."""

    def __init__(self, wid, origin=(0, 0), size=(0, 0), parent=None):
        self.id = wid
        self._origin = origin
        self._size = size
        self._parent = parent
        self._children = []
        if parent is not None:
            parent._children.append(self)

    def translate_coords(self, src, x, y):
        rx = src._origin[0] - self._origin[0] + x
        ry = src._origin[1] - self._origin[1] + y
        child = 0  # python-xlib parses X.NONE as raw int 0
        for ch in reversed(self._children):  # last-added = topmost
            cx, cy = ch._origin
            cw, chh = ch._size
            if cx <= rx < cx + cw and cy <= ry < cy + chh:
                child = ch
                break
        return SimpleNamespace(x=rx, y=ry, child=child)

    def get_geometry(self):
        return SimpleNamespace(width=self._size[0], height=self._size[1])

    def query_tree(self):
        # python-xlib returns raw int 0 for the parent of the root.
        return SimpleNamespace(
            parent=self._parent if self._parent is not None else 0)


class _FakeDisplay:
    def __init__(self, root, windows):
        self._root = root
        self._windows = {w.id: w for w in windows}

    def screen(self):
        return SimpleNamespace(root=self._root)

    def create_resource_object(self, kind, wid):
        return self._windows[wid]


def _hierarchy():
    """root(0x1) -> frame(0xF0)@(100,80) 820x630 -> client(0x77)@(110,90)
    800x600; root -> other toplevel(0xA0)@(1000,0) 400x300."""
    root = _FakeWindow(0x1, (0, 0), (3840, 2160))
    frame = _FakeWindow(0xF0, (100, 80), (820, 630), parent=root)
    client = _FakeWindow(0x77, (110, 90), (800, 600), parent=frame)
    other = _FakeWindow(0xA0, (1000, 0), (400, 300), parent=root)
    return root, frame, client, other


def _patch(monkeypatch):
    root, frame, client, other = _hierarchy()
    disp = _FakeDisplay(root, [root, frame, client, other])
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: disp)
    return root, frame, client, other


def test_get_window_geometry_origin_and_size(monkeypatch):
    # Exact positive origin pins the translate_coords direction: the
    # swapped-args form would return (-110, -90) here (historical bug).
    _patch(monkeypatch)
    assert x11_discovery.get_window_geometry(str(0x77)) == (110, 90, 800, 600)


def test_get_window_geometry_no_display(monkeypatch):
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: None)
    assert x11_discovery.get_window_geometry("119") is None


def test_toplevel_at_point_finds_each_frame(monkeypatch):
    _patch(monkeypatch)
    assert x11_discovery.toplevel_at_point(150, 100) == str(0xF0)
    assert x11_discovery.toplevel_at_point(1100, 50) == str(0xA0)


def test_toplevel_at_point_over_root_returns_empty(monkeypatch):
    # No toplevel contains the point (child raw int 0 = X.NONE): a clean
    # miss is "" — distinct from None, which means lookup FAILURE.
    _patch(monkeypatch)
    assert x11_discovery.toplevel_at_point(3000, 2000) == ""


def test_toplevel_at_point_failure_returns_none(monkeypatch):
    monkeypatch.setattr(x11_discovery, "_open_display", lambda: None)
    assert x11_discovery.toplevel_at_point(10, 10) is None


def test_toplevel_ancestor_multi_hop_walk(monkeypatch):
    # Reparenting-WM case: client -> frame -> root takes one real
    # iteration before the root match; the frame is the answer.
    _patch(monkeypatch)
    assert x11_discovery.toplevel_ancestor(str(0x77)) == str(0xF0)


def test_toplevel_ancestor_direct_child_of_root(monkeypatch):
    _patch(monkeypatch)
    assert x11_discovery.toplevel_ancestor(str(0xA0)) == str(0xA0)


def test_toplevel_ancestor_of_root_itself_returns_none(monkeypatch):
    # The root's parent parses as raw int 0 -> the parent==0 branch.
    _patch(monkeypatch)
    assert x11_discovery.toplevel_ancestor(str(0x1)) is None
