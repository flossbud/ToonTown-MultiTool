"""Pin the QGraphicsView wrapper contract for full-mode 1.5x scaling.

These tests assert that:
- _FullLayout wraps an inner _FullContent in a QGraphicsView + QGraphicsScene + QGraphicsProxyWidget.
- The view's transform is exactly 1.5x in both axes.
- The proxy holds the _FullContent instance.
- The inner cards stay at compact width (the scale is purely visual via the view's transform).
- Scrollbars are disabled (we rely on the raised W_FULL trigger to guarantee fit).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QGraphicsView, QGraphicsScene, QGraphicsProxyWidget
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()
    return tab


def test_full_layout_view_is_graphics_view(qapp, tmp_path, monkeypatch):
    """_FullLayout exposes _view as a QGraphicsView."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert isinstance(tab._full._view, QGraphicsView)


def test_full_layout_scale_is_1_5x(qapp, tmp_path, monkeypatch):
    """The view's transform applies a uniform 1.5x scale on both axes."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    transform = tab._full._view.transform()
    # m11 / m22 are the X / Y scale factors of QTransform.
    assert transform.m11() == pytest.approx(1.5)
    assert transform.m22() == pytest.approx(1.5)


def test_full_layout_proxy_holds_content(qapp, tmp_path, monkeypatch):
    """The QGraphicsScene contains a QGraphicsProxyWidget whose widget()
    is the _FullContent instance exposed as tab._full._content."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    scene_items = tab._full._scene.items()
    proxies = [it for it in scene_items if isinstance(it, QGraphicsProxyWidget)]
    assert len(proxies) == 1
    assert proxies[0].widget() is tab._full._content


def test_full_layout_inner_card_width_is_compact_width(qapp, tmp_path, monkeypatch):
    """Inner cards remain at _LOCKED_CONTENT_WIDTH — the 1.5x scale is
    purely visual via the view's transform, not baked into widget sizes.

    Precondition: _view must exist; otherwise this test is vacuously
    true today because the current _FullLayout already exposes
    _card_slots with cards pinned to _LOCKED_CONTENT_WIDTH. The
    assertion is meaningful only after Task 2 introduces the
    QGraphicsView wrapper."""
    from tabs.multitoon._compact_layout import _LOCKED_CONTENT_WIDTH

    tab = _build_tab(qapp, tmp_path, monkeypatch)

    # Precondition: wrapper must be in place. Fails today with
    # AttributeError; passes after Task 2.
    assert isinstance(tab._full._view, QGraphicsView), (
        "precondition: _FullLayout must expose a _view (QGraphicsView). "
        "If this fails, Task 2 hasn't landed yet — the inner-width "
        "assertion below would be a vacuous regression guard."
    )

    for i in range(4):
        card = tab._full._card_slots[i]["card"]
        assert card.minimumWidth() == _LOCKED_CONTENT_WIDTH
        assert card.maximumWidth() == _LOCKED_CONTENT_WIDTH


def test_full_layout_scrollbars_disabled(qapp, tmp_path, monkeypatch):
    """Both scrollbar policies are AlwaysOff. The raised W_FULL trigger
    guarantees the scaled content fits horizontally; vertically the
    layout is sized to fit any reasonable window."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert tab._full._view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert tab._full._view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
