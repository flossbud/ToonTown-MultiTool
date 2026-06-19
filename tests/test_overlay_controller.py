import pytest
from PySide6.QtWidgets import QMainWindow, QWidget, QStackedWidget, QLabel
from utils.overlay.mode import WindowMode
from utils.overlay.controller import WindowModeController


class _StubBackend:
    def __init__(self, available=True): self._a = available
    def is_available(self): return self._a
    def set_overlay_hints(self, win): self.hinted = True
    def apply_input_region(self, win, region): self.applied = True
    def clear_input_region(self, win): self.cleared = True


class _Host(QMainWindow):
    def __init__(self):
        super().__init__()
        self.header = QLabel("hdr"); self.chip_rail = QLabel("chips")
        self.update_banner = QLabel("upd"); self.admin_notice_banner = QLabel("adm")
        self.multitoon_tab = QWidget()
        self.stack = QStackedWidget(); self.stack.addWidget(self.multitoon_tab)
        self.stack.addWidget(QWidget())
        self.setCentralWidget(self.stack)
        for w in (self.header, self.chip_rail, self.update_banner, self.admin_notice_banner):
            w.setParent(self); w.show()


@pytest.fixture
def host(qapp):  # qapp = shared QApplication fixture (see Task 1.3)
    h = _Host(); h.show(); yield h; h.close()


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
    c.enter_transparent(); c.leave_transparent()
    assert c.mode() is WindowMode.FRAMED
    assert host.header.isVisible() and host.chip_rail.isVisible()
    assert host.stack.currentIndex() == 1


def test_toggle_flips(host):
    c = WindowModeController(host, _StubBackend(), settings=None)
    c.toggle(); assert c.mode() is WindowMode.TRANSPARENT
    c.toggle(); assert c.mode() is WindowMode.FRAMED


def test_cannot_enter_when_backend_unavailable(host):
    c = WindowModeController(host, _StubBackend(available=False), settings=None)
    c.toggle()
    assert c.mode() is WindowMode.FRAMED  # gated
