# tests/test_window_corner_state.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout


class _StubSettings:
    def __init__(self, **kv): self._kv = kv
    def get(self, k, d=None): return self._kv.get(k, d)
    def set(self, k, v): self._kv[k] = v


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make(qapp, native=False):
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    QMainWindow.__init__(inst)
    inst.settings_manager = _StubSettings(
        use_system_title_bar=native, hints_enabled=True, theme="dark")
    inst.header = inst._build_header()
    inst.container = QWidget()
    root = QVBoxLayout()
    root.addWidget(inst.header)
    inst.container.setLayout(root)
    inst.setCentralWidget(inst.container)
    inst._chrome = None if native else object()  # stand-in so frameless branch is taken
    inst.container.setObjectName("app_card")
    return inst, root


def test_corner_state_normal_rounds_and_insets(qapp):
    inst, root = _make(qapp, native=False)
    inst._apply_window_corner_state(is_maximized=False)
    assert "border-radius: 16px" in inst.container.styleSheet()
    m = root.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (1, 1, 1, 16)
    assert "border-top-left-radius: 15px" in inst.header.styleSheet()


def test_corner_state_preserves_bg_cascade_to_descendants(qapp):
    # Regression: the container must still emit a bare, unprefixed
    # `QWidget { background: bg_app }` rule so descendant widgets inherit the
    # app background (several tabs rely on this cascade). The object-scoped
    # #app_card rule alone would not cascade.
    for maxed in (False, True):
        inst, _root = _make(qapp, native=False)
        inst._apply_window_corner_state(is_maximized=maxed)
        ss = inst.container.styleSheet()
        assert "QWidget {" in ss, f"missing bg cascade rule (maximized={maxed}): {ss!r}"
        # native path too
    inst, _root = _make(qapp, native=True)
    inst._apply_window_corner_state(is_maximized=False)
    assert "QWidget {" in inst.container.styleSheet()


def test_corner_state_maximized_is_square(qapp):
    inst, root = _make(qapp, native=False)
    inst._apply_window_corner_state(is_maximized=True)
    assert "border-radius" not in inst.container.styleSheet()
    m = root.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)
    assert "border-top-left-radius: 0px" in inst.header.styleSheet()


def test_corner_state_native_is_plain(qapp):
    inst, root = _make(qapp, native=True)
    inst._apply_window_corner_state(is_maximized=False)
    assert "border-radius" not in inst.container.styleSheet()
    m = root.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)


def test_changeevent_restyles_on_window_state_change(qapp, monkeypatch):
    from PySide6.QtCore import QEvent
    inst, root = _make(qapp, native=False)
    calls = []
    monkeypatch.setattr(inst, "_apply_window_corner_state", lambda is_maximized: calls.append(is_maximized))
    inst.changeEvent(QEvent(QEvent.WindowStateChange))
    assert calls, "WindowStateChange should re-apply the corner state"
