"""Tests for utils.keyring_macos_stub.

Locks the contract: on non-Darwin hosts, install_stub() must put a module
object in sys.modules under the name "keyring.backends.macOS.api" before
any keyring import runs. If this regresses, the AppImage and Flatpak go
back to ~60% SIGABRT-on-launch on Linux.
"""

import sys
import types
from unittest.mock import patch

import pytest

from utils.keyring_macos_stub import install_stub, _STUB_MODULE_NAME


@pytest.fixture(autouse=True)
def _clean_sys_modules():
    """Remove the stub between tests so each test sees a clean slate."""
    saved = sys.modules.pop(_STUB_MODULE_NAME, None)
    yield
    if saved is not None:
        sys.modules[_STUB_MODULE_NAME] = saved
    else:
        sys.modules.pop(_STUB_MODULE_NAME, None)


class TestInstallStub:
    def test_installs_stub_on_linux(self):
        with patch.object(sys, "platform", "linux"):
            assert _STUB_MODULE_NAME not in sys.modules
            assert install_stub() is True
            assert _STUB_MODULE_NAME in sys.modules
            assert isinstance(sys.modules[_STUB_MODULE_NAME], types.ModuleType)

    def test_installs_stub_on_windows(self):
        """Windows packaging hits the same dangling-class state if the
        macOS backend gets enumerated by entry_points discovery."""
        with patch.object(sys, "platform", "win32"):
            assert install_stub() is True
            assert _STUB_MODULE_NAME in sys.modules

    def test_skipped_on_darwin(self):
        """On macOS the real api.py imports fine; do not shadow it."""
        with patch.object(sys, "platform", "darwin"):
            assert install_stub() is False
            assert _STUB_MODULE_NAME not in sys.modules

    def test_idempotent_does_not_replace_existing(self):
        """If the real module (or an earlier stub) is already loaded, leave
        it alone. setdefault-style behavior keeps a real-on-Darwin import
        from being shadowed if the call somehow re-fires."""
        sentinel = types.ModuleType(_STUB_MODULE_NAME)
        sentinel.marker = object()
        sys.modules[_STUB_MODULE_NAME] = sentinel
        with patch.object(sys, "platform", "linux"):
            assert install_stub() is True
            assert sys.modules[_STUB_MODULE_NAME] is sentinel

    def test_keyring_backends_macOS_init_finds_stub(self):
        """The actual integration we depend on: keyring's macOS backend
        package init does `from . import api`. With our stub in place, that
        import resolves to the stub via sys.modules cache and the real
        failing api.py never runs.

        We assert the cache-hit behavior at the importlib level rather than
        importing keyring (which would have side effects on the test
        process)."""
        import importlib

        with patch.object(sys, "platform", "linux"):
            install_stub()
            mod = importlib.import_module(_STUB_MODULE_NAME)
            assert mod is sys.modules[_STUB_MODULE_NAME]
