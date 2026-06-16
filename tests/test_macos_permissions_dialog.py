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
