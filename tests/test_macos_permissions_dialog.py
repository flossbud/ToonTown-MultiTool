import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
import pytest
from PySide6.QtWidgets import QApplication
from utils import macos_permissions as mp


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeNative:
    def __init__(self, ax, im): self.ax, self.im = ax, im
    def accessibility_granted(self): return self.ax
    def input_monitoring_granted(self): return self.im
    def request_accessibility(self): pass
    def request_input_monitoring(self): pass


def test_dialog_builds_and_reflects_status(qapp):
    from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=False))
    dlg = MacOSPermissionsDialog(pm, location_ok=True)
    try:
        dlg.refresh()
        assert dlg.row_state("accessibility") == "granted"
        assert dlg.row_state("input_monitoring") in ("request", "open_settings")
    finally:
        dlg.deleteLater()


def test_dialog_shows_move_prompt_when_location_bad(qapp):
    from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
    pm = mp.PermissionManager(native=_FakeNative(ax=False, im=False))
    dlg = MacOSPermissionsDialog(pm, location_ok=False)
    try:
        assert dlg.is_move_required() is True
    finally:
        dlg.deleteLater()


def test_clt_row_missing_offers_install(qapp, monkeypatch):
    """CLT absent -> the row shows actionable Install (NOT gating the perm rows)."""
    from utils.widgets import macos_permissions_dialog as dlg_mod
    from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
    monkeypatch.setattr(
        dlg_mod.macos_clt, "clt_state",
        lambda: (False, "Mouse click sync needs Xcode Command Line Tools", None))
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=True))
    dlg = MacOSPermissionsDialog(pm, location_ok=True)
    try:
        assert dlg.clt_present() is False
        assert dlg._clt_btn.text() == "Install"
        assert dlg._clt_btn.isEnabled() is True
        assert dlg._clt_status.text() == "Not installed"
        # Mouse-only: the keyboard/accessibility rows are not gated on CLT.
        assert dlg.row_state("accessibility") == "granted"
    finally:
        dlg.deleteLater()


def test_clt_probe_is_ttl_cached_not_per_refresh(qapp, monkeypatch):
    """clt_state() forks xcode-select; the 1s refresh timer must not re-fork every
    tick. A second refresh inside the TTL window reuses the cached result."""
    from utils.widgets import macos_permissions_dialog as dlg_mod
    from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
    calls = {"n": 0}

    def counting_state():
        calls["n"] += 1
        return (False, "Mouse click sync needs Xcode Command Line Tools", None)

    monkeypatch.setattr(dlg_mod.macos_clt, "clt_state", counting_state)
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=True))
    dlg = MacOSPermissionsDialog(pm, location_ok=True)
    try:
        first = calls["n"]            # construction's refresh probed once
        assert first >= 1
        dlg.refresh()                 # within the TTL window -> cache hit, no new fork
        assert calls["n"] == first
    finally:
        dlg.deleteLater()


def test_clt_row_present_is_satisfied(qapp, monkeypatch):
    """CLT present -> the row shows satisfied (disabled), like a granted perm row."""
    from utils.widgets import macos_permissions_dialog as dlg_mod
    from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
    monkeypatch.setattr(
        dlg_mod.macos_clt, "clt_state",
        lambda: (True, None, "/Library/Developer/CommandLineTools/usr/bin/python3"))
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=True))
    dlg = MacOSPermissionsDialog(pm, location_ok=True)
    try:
        assert dlg.clt_present() is True
        assert dlg._clt_status.text() == "Installed"
        assert dlg._clt_btn.isEnabled() is False
    finally:
        dlg.deleteLater()
