"""Tests for the macOS keyboard-layout shim that keeps pynput's listener thread
from calling Text-Input-Source (TIS) APIs.

Root cause (see utils/macos_keyboard_layout.py): pynput's keyboard listener
fetches the keyboard layout via keycode_context() on its BACKGROUND listener
thread; on macOS the TIS/TSM input-source APIs must run on the main thread and
trap (SIGTRAP) off-main around input-source/focus transitions. The shim fetches
the layout once on the main thread and replaces pynput's keycode_context with a
no-TIS context manager yielding the cached layout, so the listener thread never
calls TIS.

These tests stub the REAL keycode_context with a tracker (so no Carbon TIS runs)
and assert the contract: the real fetch happens exactly once, on the installing
(main) thread, and the installed shim — what the listener thread enters — yields
the cached layout WITHOUT re-invoking the real TIS fetch.
"""
from __future__ import annotations

import contextlib
import sys
import threading

import pytest

import utils.macos_keyboard_layout as klm


@pytest.fixture(autouse=True)
def _reset_installed(monkeypatch):
    # The installer is idempotent via a module flag; reset it per test so each
    # test exercises a fresh install (monkeypatch restores it afterwards).
    monkeypatch.setattr(klm, "_installed", False, raising=False)
    yield


def _install_with_tracked_real_ctx(monkeypatch):
    """Replace the REAL pynput keycode_context (and the keyboard-module alias)
    with a tracker that records the calling thread and yields a sentinel layout,
    then install the shim. Returns (calls, sentinel)."""
    monkeypatch.setattr(sys, "platform", "darwin")
    import pynput._util.darwin as pyd
    import pynput.keyboard._darwin as kbd

    calls = []
    sentinel = ("KBTYPE", b"LAYOUT-DATA")

    @contextlib.contextmanager
    def _tracked_real_ctx():
        calls.append(threading.current_thread().name)
        yield sentinel

    # monkeypatch saves the genuine originals and restores them at teardown,
    # which also undoes the shim install() performs on kbd.keycode_context.
    monkeypatch.setattr(pyd, "keycode_context", _tracked_real_ctx)
    monkeypatch.setattr(kbd, "keycode_context", _tracked_real_ctx)

    ok = klm.install_main_thread_keycode_context()
    return ok, calls, sentinel, kbd, _tracked_real_ctx


def test_install_fetches_layout_once_on_main_and_shims_keyboard_module(monkeypatch):
    ok, calls, sentinel, kbd, tracked = _install_with_tracked_real_ctx(monkeypatch)
    assert ok is True
    # The real TIS fetch ran exactly once, on the installing (this/main) thread.
    assert calls == [threading.current_thread().name]
    # The keyboard module's keycode_context is now the SHIM, not the real fetch.
    assert kbd.keycode_context is not tracked


def test_listener_thread_entering_shim_does_not_call_real_tis(monkeypatch):
    ok, calls, sentinel, kbd, tracked = _install_with_tracked_real_ctx(monkeypatch)
    assert ok is True
    assert len(calls) == 1  # the main-thread precompute

    # Simulate the pynput listener thread entering keycode_context (what _run
    # does). It must yield the cached layout and NOT call the real TIS fetch.
    result = {}

    def _bg():
        with kbd.keycode_context() as ctx:
            result["ctx"] = ctx

    t = threading.Thread(target=_bg, name="pynput-listener")
    t.start()
    t.join()

    assert result["ctx"] == sentinel        # shim yielded the cached layout
    assert len(calls) == 1                   # real TIS fetch NOT re-invoked off-main


def test_install_is_idempotent(monkeypatch):
    ok, calls, sentinel, kbd, tracked = _install_with_tracked_real_ctx(monkeypatch)
    assert ok is True
    assert len(calls) == 1
    # Second install is a no-op: no additional TIS fetch.
    assert klm.install_main_thread_keycode_context() is True
    assert len(calls) == 1


def test_install_noop_off_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert klm.install_main_thread_keycode_context() is False


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="exercises pynput's real macOS Listener._run")
def test_pynput_run_resolves_patched_keycode_context_global(monkeypatch):
    """Upgrade guard (peer review): pynput's REAL darwin Listener._run must
    resolve the keyboard-module `keycode_context` GLOBAL (the exact symbol the
    shim replaces). If a future pynput captured it differently / moved it, _run
    would bypass our shim and the off-main TIS crash would return -- this test
    fails in that case. Stub the base run loop so no real CGEventTap is created."""
    import pynput.keyboard._darwin as kbd
    from pynput._util.darwin import ListenerMixin

    marker = ("PROBE_KBTYPE", b"PROBE_LAYOUT")

    @contextlib.contextmanager
    def _probe_ctx():
        yield marker

    # What _run SHOULD resolve and enter (the keyboard-module global):
    monkeypatch.setattr(kbd, "keycode_context", _probe_ctx)
    captured = {}
    monkeypatch.setattr(
        ListenerMixin, "_run",
        lambda self: captured.__setitem__("ctx", self._context))

    listener = kbd.Listener(on_press=lambda k: None, on_release=lambda k: None)
    listener._run()  # real darwin _run: 'with keycode_context() as c: self._context=c; super()._run()'

    assert captured["ctx"] == marker  # _run resolved + entered the patched global


def test_start_listener_skips_when_shim_unavailable_on_darwin(monkeypatch):
    """Fail-safe (peer review): if the shim could not be installed on darwin,
    HotkeyManager must NOT start the pynput listener (which would SIGTRAP);
    capture degrades to off."""
    from services.hotkey_manager import HotkeyManager
    monkeypatch.setattr(sys, "platform", "darwin")
    hk = HotkeyManager.__new__(HotkeyManager)
    hk.is_listening = False
    hk.listener = None
    hk._darwin_capture_ready = False
    hk._darwin_capture_warned = False
    hk._start_listener()
    assert hk.listener is None       # listener NOT started (crash avoided)
    assert hk.is_listening is False
