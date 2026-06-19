import pytest
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QLabel,
)
from utils.overlay.mode import WindowMode
from utils.overlay.controller import WindowModeController


class _StubBackend:
    def __init__(self, available=True):
        self._a = available
        self.apply_count = 0
        self.clear_count = 0
        self.hinted = False

    def is_available(self):
        return self._a

    def set_overlay_hints(self, win):
        self.hinted = True

    def apply_input_region(self, win, region):
        self.apply_count += 1

    def clear_input_region(self, win):
        self.clear_count += 1


class _CompactStub(QWidget):
    """Minimal _CompactLayout stand-in exposing the two path accessors."""

    def card_body_paths(self):
        p = QPainterPath()
        p.addRoundedRect(0, 0, 100, 150, 10, 10)
        return [p]

    def emblem_path(self):
        p = QPainterPath()
        p.addEllipse(40, 140, 20, 20)
        return p


class _MultitoonTabStub(QWidget):
    """Minimal multitoon_tab with _compact and _stack."""

    def __init__(self):
        super().__init__()
        self._compact = _CompactStub()
        self._stack = QStackedWidget()
        self._stack.addWidget(self._compact)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)


class _Host(QMainWindow):
    def __init__(self):
        super().__init__()
        self.header = QLabel("hdr")
        self.chip_rail = QLabel("chips")
        self.update_banner = QLabel("upd")
        self.admin_notice_banner = QLabel("adm")

        self.multitoon_tab = _MultitoonTabStub()

        # window-level stack (mirrors real app's self._win.stack)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.multitoon_tab)
        self.stack.addWidget(QWidget())

        # container is the central widget with a QVBoxLayout (mirrors real app)
        self.container = QWidget()
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.stack)
        self.setCentralWidget(self.container)

        for w in (self.header, self.chip_rail, self.update_banner, self.admin_notice_banner):
            w.setParent(self)
            w.show()


@pytest.fixture
def host(qapp):  # qapp = shared QApplication fixture (see Task 1.3)
    h = _Host()
    h.show()
    yield h
    h.close()


# ---------------------------------------------------------------------------
# Phase-1 regression tests (must stay green)
# ---------------------------------------------------------------------------

def test_enter_hides_chrome_and_forces_multitoon(host):
    host.stack.setCurrentIndex(1)
    c = WindowModeController(host, _StubBackend(), settings=None)
    c.enter_transparent()
    assert c.mode() is WindowMode.TRANSPARENT
    assert not host.header.isVisible() and not host.chip_rail.isVisible()
    assert host.stack.currentWidget() is host.multitoon_tab


def test_leave_restores_chrome_and_tab(host):
    host.stack.setCurrentIndex(1)
    c = WindowModeController(host, _StubBackend(), settings=None)
    c.enter_transparent()
    c.leave_transparent()
    assert c.mode() is WindowMode.FRAMED
    assert host.header.isVisible() and host.chip_rail.isVisible()
    assert host.stack.currentIndex() == 1


def test_toggle_flips(host):
    c = WindowModeController(host, _StubBackend(), settings=None)
    c.toggle()
    assert c.mode() is WindowMode.TRANSPARENT
    c.toggle()
    assert c.mode() is WindowMode.FRAMED


def test_cannot_enter_when_backend_unavailable(host):
    c = WindowModeController(host, _StubBackend(available=False), settings=None)
    c.toggle()
    assert c.mode() is WindowMode.FRAMED  # gated


# ---------------------------------------------------------------------------
# Phase-3 tests: overlay hooks, region, scale
# ---------------------------------------------------------------------------

def test_enter_applies_input_region(host):
    """_apply_overlay must call apply_input_region exactly once (via update_region)."""
    backend = _StubBackend()
    c = WindowModeController(host, backend, settings=None)
    c.enter_transparent()
    assert backend.apply_count >= 1


def test_set_scale_reapplies_region(host):
    """set_scale_by_notches must advance the host scale and call apply_input_region again."""
    backend = _StubBackend()
    c = WindowModeController(host, backend, settings=None)
    c.enter_transparent()
    initial_scale = c._host.current_scale()
    count_after_enter = backend.apply_count

    c.set_scale_by_notches(1)

    assert c._host.current_scale() != initial_scale, "scale must change after +1 notch"
    assert backend.apply_count > count_after_enter, "apply_input_region must be called again"


def test_leave_restores_cluster_to_stack(host):
    """After leave, _compact must be back in multitoon_tab._stack and _host must be None."""
    c = WindowModeController(host, _StubBackend(), settings=None)
    c.enter_transparent()
    # compact was reparented into the ClusterHost scene
    c.leave_transparent()
    compact = host.multitoon_tab._compact
    assert host.multitoon_tab._stack.indexOf(compact) >= 0, (
        "_compact must be back in multitoon_tab._stack after leave"
    )
    assert c._host is None


def test_set_scale_by_notches_is_noop_in_framed_mode(host):
    """set_scale_by_notches must be a safe no-op (no AttributeError) when in framed mode."""
    c = WindowModeController(host, _StubBackend(), settings=None)
    assert c._host is None
    c.set_scale_by_notches(1)  # must not raise
