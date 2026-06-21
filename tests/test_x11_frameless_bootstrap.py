from utils import x11_frameless_bootstrap as fb


def test_native_when_user_forces_title_bar():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name="GNOME Shell", use_system_title_bar=True, cached_mode=None,
    ) == fb.NATIVE_TITLE_BAR


def test_pure_frameless_off_linux():
    assert fb.resolve_window_mode(
        platform="darwin", session_type="", qpa_platform="cocoa",
        wm_name=None, use_system_title_bar=False, cached_mode=None,
    ) == fb.PURE_FRAMELESS


def test_pure_frameless_on_x11_session():
    assert fb.resolve_window_mode(
        platform="linux", session_type="x11", qpa_platform="xcb",
        wm_name="GNOME Shell", use_system_title_bar=False, cached_mode=None,
    ) == fb.PURE_FRAMELESS


def test_pure_frameless_when_not_xwayland():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="wayland",
        wm_name="GNOME Shell", use_system_title_bar=False, cached_mode=None,
    ) == fb.PURE_FRAMELESS


def test_pure_frameless_on_known_good_wm():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name="KWin", use_system_title_bar=False, cached_mode=None,
    ) == fb.PURE_FRAMELESS


def test_frame_then_strip_on_mutter_xwayland():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name="GNOME Shell", use_system_title_bar=False, cached_mode=None,
    ) == fb.FRAME_THEN_STRIP


def test_cached_runtime_fallback_is_honored():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name="GNOME Shell", use_system_title_bar=False, cached_mode=fb.BORDER_ONLY,
    ) == fb.BORDER_ONLY


def test_cached_pure_frameless_is_ignored_when_gating_says_bootstrap():
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name="GNOME Shell", use_system_title_bar=False, cached_mode=fb.PURE_FRAMELESS,
    ) == fb.FRAME_THEN_STRIP


def test_motif_values():
    assert fb.motif_hints_value(fb.DECOR_ALL) == [2, 0, 1, 0, 0]
    assert fb.motif_hints_value(fb.DECOR_NONE) == [2, 0, 0, 0, 0]
    assert fb.motif_hints_value(fb.DECOR_BORDER) == [2, 0, 2, 0, 0]


def test_environment_signature_stable_and_distinct():
    a = fb.environment_signature(qpa_platform="xcb", session_type="wayland",
                                 wm_name="GNOME Shell", qt_version="6.10.2")
    b = fb.environment_signature(qpa_platform="xcb", session_type="wayland",
                                 wm_name="GNOME Shell", qt_version="6.10.2")
    c = fb.environment_signature(qpa_platform="xcb", session_type="wayland",
                                 wm_name="KWin", qt_version="6.10.2")
    assert a == b and a != c


class _FakeProp:
    def __init__(self, value): self.value = value

class _FakeWindow:
    def __init__(self, props): self._props = props
    def get_full_property(self, atom, _type):
        return self._props.get(atom)

class _FakeScreen:
    def __init__(self, root): self.root = root

class _FakeDisplay:
    def __init__(self, wm_name=None, support_id=4242):
        self._atoms = {}
        self._next = 1
        self._support_atom = self.intern_atom("_NET_SUPPORTING_WM_CHECK")
        self._name_atom = self.intern_atom("_NET_WM_NAME")
        root_props = {self._support_atom: _FakeProp([support_id])} if support_id else {}
        self._root = _FakeWindow(root_props)
        check_props = {}
        if wm_name is not None:
            check_props[self._name_atom] = _FakeProp(wm_name.encode("utf-8"))
        self._check = _FakeWindow(check_props)
        self._support_id = support_id
    def intern_atom(self, name):
        if name not in self._atoms:
            self._atoms[name] = self._next; self._next += 1
        return self._atoms[name]
    def screen(self): return _FakeScreen(self._root)
    def create_resource_object(self, _kind, wid):
        return self._check if wid == self._support_id else _FakeWindow({})


def test_detect_wm_name_reads_supporting_check():
    d = _FakeDisplay(wm_name="GNOME Shell")
    assert fb.detect_wm_name(d) == "GNOME Shell"


def test_detect_wm_name_none_when_no_support_window():
    d = _FakeDisplay(wm_name=None, support_id=0)
    assert fb.detect_wm_name(d) is None


class _DictSettings:
    def __init__(self, **kv): self._kv = dict(kv)
    def get(self, k, d=None): return self._kv.get(k, d)
    def set(self, k, v): self._kv[k] = v


def test_cache_roundtrip_same_signature():
    s = _DictSettings()
    fb.cache_resolved_mode(s, "sig-A", fb.BORDER_ONLY)
    assert fb.cached_mode_for(s, "sig-A") == fb.BORDER_ONLY


def test_cache_miss_on_different_signature():
    s = _DictSettings()
    fb.cache_resolved_mode(s, "sig-A", fb.NATIVE_TITLE_BAR)
    assert fb.cached_mode_for(s, "sig-B") is None


def test_frame_then_strip_on_unknown_wm():
    # Unknown WM (None) on XWayland: default to bootstrap rather than skip it.
    assert fb.resolve_window_mode(
        platform="linux", session_type="wayland", qpa_platform="xcb",
        wm_name=None, use_system_title_bar=False, cached_mode=None,
    ) == fb.FRAME_THEN_STRIP


def test_detect_wm_name_none_when_support_window_has_no_name():
    # Support window present but _NET_WM_NAME absent -> None.
    d = _FakeDisplay(wm_name=None, support_id=4242)
    assert fb.detect_wm_name(d) is None
