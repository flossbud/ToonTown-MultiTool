"""Tests for the topmost re-assert + reshape-on-screen-change (Task 7.1):
the controller re-applies ABOVE on every surface + the emblem-above-cards z-order
on enter, on a scale change, on update_shapes, and on a low-frequency timer while
transparent; and reshapes when a surface changes monitor/DPI.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_overlay_topmost.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.group_controller import OverlayGroupController


class _AboveSpyBackend(NoOpOverlayBackend):
    def __init__(self):
        self.above_calls = []
        self.skip_taskbar_calls = []

    def set_above(self, window):
        self.above_calls.append(window)

    def set_non_activating(self, window):
        self.skip_taskbar_calls.append(window)


class _FakeSignal:
    """A minimal screenChanged stand-in so the tests exercise the REAL
    _connect_screen_change wiring (not just the _on_screen_changed guard)."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeWindowHandle:
    def __init__(self):
        self.screenChanged = _FakeSignal()


class _StubSurface:
    def __init__(self):
        self.raises = 0
        self._handle = _FakeWindowHandle()

    def prepare_initial_state(self):
        pass

    def set_overlay_geometry(self, rect):
        pass

    def show(self):
        pass

    def hide(self):
        pass

    def apply_shape(self, path, dpr):
        pass

    def raise_(self):
        self.raises += 1

    def release(self):
        return None

    def close(self):
        pass

    def deleteLater(self):
        pass

    def devicePixelRatio(self):
        return 1.0

    def windowHandle(self):
        return self._handle


class _StubFactory:
    def __init__(self):
        self.created = []

    def __call__(self, state):
        s = _StubSurface()
        self.created.append(s)
        return s


class _Win:
    def showMinimized(self):
        pass

    def showNormal(self):
        pass


def _ctl():
    backend = _AboveSpyBackend()
    factory = _StubFactory()
    ctl = OverlayGroupController(_Win(), backend=backend, surface_factory=factory)
    return ctl, backend, factory


def test_enter_reasserts_above_on_all_surfaces_and_starts_timer(qapp):
    ctl, backend, factory = _ctl()
    assert ctl.enter() is True
    # ABOVE re-asserted on each of the 5 surfaces.
    assert len(backend.above_calls) == 5
    assert set(backend.above_calls) == set(factory.created)
    # The ~1.5s re-assert timer runs while transparent...
    assert ctl._above_timer is not None and ctl._above_timer.isActive()
    # ...and its timeout is wired to the re-assert (forcing it re-applies ABOVE).
    backend.above_calls.clear()
    ctl._above_timer.timeout.emit()
    assert len(backend.above_calls) == 5
    ctl.leave()
    assert not ctl._above_timer.isActive()  # ...and stops on leave


def test_reassert_topmost_also_rehides_from_taskbar(qapp):
    # KWin can re-add the surfaces to the taskbar after the main window minimizes,
    # so the re-assert must re-apply skip-taskbar (set_non_activating), not just ABOVE.
    ctl, backend, factory = _ctl()
    ctl.enter()
    backend.skip_taskbar_calls.clear()
    ctl._reassert_topmost()
    assert len(backend.skip_taskbar_calls) == 5
    assert set(backend.skip_taskbar_calls) == set(factory.created)
    ctl.leave()


def test_reassert_topmost_raises_emblem_last(qapp):
    ctl, backend, factory = _ctl()
    ctl.enter()
    before = factory.created[-1].raises
    backend.above_calls.clear()
    ctl._reassert_topmost()
    assert len(backend.above_calls) == 5
    assert factory.created[-1].raises == before + 1  # emblem (last surface) re-raised
    ctl.leave()


def test_update_shapes_reasserts_above(qapp):
    ctl, backend, factory = _ctl()
    ctl.enter()
    backend.above_calls.clear()
    ctl.update_shapes()
    assert len(backend.above_calls) == 5
    ctl.leave()


def test_scale_change_reasserts_above(qapp):
    # The provider=None scale branch must also re-apply ABOVE after a notch.
    ctl, backend, factory = _ctl()
    ctl.enter()
    backend.above_calls.clear()
    ctl.set_scale_by_notches(1)
    assert len(backend.above_calls) == 5
    ctl.leave()


def test_screen_change_signal_reshapes_via_real_wiring(qapp):
    # Exercise the REAL _connect_screen_change path: emitting screenChanged on the
    # emblem (last) surface's window handle must reshape the cluster.
    ctl, backend, factory = _ctl()
    ctl.enter()
    called = []
    ctl.update_shapes = lambda: called.append(1)
    factory.created[-1].windowHandle().screenChanged.emit(object())
    assert called == [1]
    # The cards (non-emblem surfaces) are NOT wired - only the emblem handle is.
    called.clear()
    factory.created[0].windowHandle().screenChanged.emit(object())
    assert called == []
    ctl.leave()


def test_on_screen_changed_reshapes_when_active(qapp):
    ctl, backend, factory = _ctl()
    ctl.enter()
    called = []
    ctl.update_shapes = lambda: called.append(1)
    ctl._on_screen_changed()
    assert called == [1]
    ctl.leave()


def test_on_screen_changed_noop_when_framed(qapp):
    ctl, backend, factory = _ctl()
    called = []
    ctl.update_shapes = lambda: called.append(1)
    ctl._on_screen_changed()  # not active
    assert called == []
