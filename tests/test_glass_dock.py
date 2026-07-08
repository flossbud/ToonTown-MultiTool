# tests/test_glass_dock.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_v2_nav_has_four_tabs_with_exact_hex():
    from utils.theme_manager import V2_NAV
    assert V2_NAV["multitoon"] == {"c": "#0077ff", "b": "#3399ff"}
    assert V2_NAV["launcher"] == {"c": "#E05252", "b": "#ea7a7a"}
    assert V2_NAV["keysets"] == {"c": "#DAA520", "b": "#e8c14d"}
    assert V2_NAV["settings"] == {"c": "#3da343", "b": "#56d66a"}


import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


NAV_ITEMS = [
    ("Multitoon", "make_nav_gamepad", "multitoon"),
    ("Launcher", "make_nav_power", "launcher"),
    ("Keysets", "make_nav_keyboard", "keysets"),
    ("Settings", "make_nav_gear", "settings"),
]


@pytest.fixture
def dock(qapp):
    from utils.widgets.glass_dock import GlassDock
    d = GlassDock(NAV_ITEMS, is_dark=True)
    d.resize(d.sizeHint())
    # Force geometry computation as if shown.
    d.show()
    QApplication.processEvents()
    return d


def test_dock_has_four_segments_in_order(dock):
    assert [s.label for s in dock.segments] == ["Multitoon", "Launcher", "Keysets", "Settings"]


def test_dock_widget_height_is_58(dock):
    assert dock.sizeHint().height() == 58


def test_segments_have_nonoverlapping_rects_left_to_right(dock):
    rects = [s.rect for s in dock.segments]
    for a, b in zip(rects, rects[1:]):
        assert a.right() <= b.left() + 1  # ordered, gap between


def test_default_selected_is_zero(dock):
    assert dock.selected_index() == 0


def test_click_segment_emits_selected(dock, qapp):
    got = []
    dock.selected.connect(got.append)
    # click center of segment index 2 (Keysets)
    seg = dock.segments[2]
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF
    center = seg.rect.center()
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(center), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    dock.mousePressEvent(ev)
    assert got == [2]


def test_select_sets_state_without_emitting(dock):
    got = []
    dock.selected.connect(got.append)
    dock.select(3)
    assert dock.selected_index() == 3
    assert got == []  # programmatic select does not re-emit


class _StubSettings:
    def __init__(self, **kv): self._kv = kv
    def get(self, k, d=None): return self._kv.get(k, d)
    def set(self, k, v): self._kv[k] = v


def _bare_main(qapp):
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    return inst


def test_nav_band_builds_with_glass_dock(qapp):
    from utils.widgets.glass_dock import GlassDock
    inst = _bare_main(qapp)
    band = inst._build_nav_band()
    assert band.objectName() == "app_nav_band"
    assert isinstance(inst.nav_dock, GlassDock)
    # Top-level Keysets tab dropped (moved into Settings > Keysets); production
    # nav is back to three segments.
    assert [s.label for s in inst.nav_dock.segments] == \
        ["Multitoon", "Launcher", "Settings"]


def test_nav_band_min_height_le_64(qapp):
    from main import NAV_BAND_H
    assert NAV_BAND_H == 60 and NAV_BAND_H <= 64


def test_dock_selected_signal_calls_nav_select(qapp, monkeypatch):
    inst = _bare_main(qapp)
    # Patch nav_select BEFORE building the band so the dock's `selected` signal
    # connects to the spy. (On a bare __new__ instance the C++ QObject is not
    # initialized, so PySide captures the connected callable at connect time
    # rather than re-resolving it by name.) Hold the band the way production
    # does so the parentless QFrame is not garbage-collected under the dock.
    calls = []
    monkeypatch.setattr(inst, "nav_select", lambda i: calls.append(i))
    inst.nav_band = inst._build_nav_band()
    inst.nav_dock.selected.emit(2)
    assert calls == [2]


# -- sliding selection pill (color-morphing) --------------------------------

def test_pill_starts_on_segment_zero(dock):
    from utils.theme_manager import V2_NAV
    from PySide6.QtGui import QColor
    assert dock._pill_rect.x() == dock.segments[0].rect.x()
    assert dock._pill_c == QColor(V2_NAV["multitoon"]["c"])


def test_reduced_motion_snaps_pill_to_selected(dock, monkeypatch):
    import utils.motion as motion
    from utils.theme_manager import V2_NAV
    from PySide6.QtGui import QColor
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    dock.select(2)
    assert dock._pill_rect.x() == dock.segments[2].rect.x()
    assert dock._pill_c == QColor(V2_NAV["keysets"]["c"])   # morphed to Keysets gold


def test_coverage_is_full_on_snapped_segment_only(dock, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    dock.select(3)
    assert dock._coverage(dock.segments[3]) == 1.0
    assert dock._coverage(dock.segments[0]) == 0.0


# -- debug overflow visibility + phantom centering (migrated from chip rail) --

def test_overflow_hidden_when_debug_off(qapp):
    inst = _bare_main(qapp)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    band = inst._build_nav_band()
    assert inst.overflow_btn.isVisibleTo(band) is False


def test_overflow_visible_when_debug_on(qapp):
    inst = _bare_main(qapp)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=True)
    band = inst._build_nav_band()
    assert inst.overflow_btn.isVisibleTo(band) is True


def test_phantom_zero_when_debug_off(qapp):
    inst = _bare_main(qapp)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    band = inst._build_nav_band()   # hold the band so its QSpacerItem survives
    assert inst.nav_left_phantom.sizeHint().width() == 0
    assert band is not None


def test_phantom_balances_overflow_when_debug_on(qapp):
    inst = _bare_main(qapp)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=True)
    band = inst._build_nav_band()   # hold the band so its QSpacerItem survives
    assert inst.nav_left_phantom.sizeHint().width() == 38  # overflow 34 + 4 gap
    assert band is not None
