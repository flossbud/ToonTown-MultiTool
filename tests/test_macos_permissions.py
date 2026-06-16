"""macOS permission onboarding logic (no PyObjC needed; APIs injected)."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
from utils import macos_permissions as mp


class _FakeNative:
    def __init__(self, ax=False, im=False):
        self.ax, self.im = ax, im
        self.ax_requested = self.im_requested = 0
    def accessibility_granted(self): return self.ax
    def input_monitoring_granted(self): return self.im
    def request_accessibility(self): self.ax_requested += 1
    def request_input_monitoring(self): self.im_requested += 1


# --- Task 9: install-location classifier ---
def test_install_location_translocated():
    assert mp.classify_location(
        "/private/var/folders/ab/xyz/T/AppTranslocation/X/d/ToonTown MultiTool.app"
    ) == "translocated"

def test_install_location_dmg():
    assert mp.classify_location("/Volumes/ToonTown MultiTool/ToonTown MultiTool.app") == "dmg"

def test_install_location_downloads():
    assert mp.classify_location(
        os.path.expanduser("~/Downloads/ToonTown MultiTool.app")) == "downloads"

def test_install_location_applications_is_ok():
    assert mp.classify_location("/Applications/ToonTown MultiTool.app") == "ok"

def test_install_location_user_applications_is_ok():
    assert mp.classify_location(
        os.path.expanduser("~/Applications/ToonTown MultiTool.app")) == "ok"

def test_is_install_location_ok():
    assert mp.is_install_location_ok("/Applications/ToonTown MultiTool.app") is True
    assert mp.is_install_location_ok("/Volumes/X/ToonTown MultiTool.app") is False


# --- Task 10: status + one-shot request aggregator ---
def test_status_reports_both():
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=False))
    s = pm.status()
    assert s["accessibility"] is True and s["input_monitoring"] is False
    assert pm.all_granted() is False

def test_all_granted_true_when_both():
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=True))
    assert pm.all_granted() is True

def test_request_is_one_shot_then_settings():
    nat = _FakeNative(ax=False, im=False)
    pm = mp.PermissionManager(native=nat)
    assert pm.next_action("accessibility") == "request"
    pm.request("accessibility")
    assert nat.ax_requested == 1
    assert pm.next_action("accessibility") == "open_settings"
    pm.request("accessibility")
    assert nat.ax_requested == 1

def test_request_input_monitoring_is_one_shot():
    # Pins the input-monitoring arm of the request dispatch (a routing swap to
    # request_accessibility would otherwise pass every other test).
    nat = _FakeNative(ax=False, im=False)
    pm = mp.PermissionManager(native=nat)
    assert pm.next_action("input_monitoring") == "request"
    pm.request("input_monitoring")
    assert nat.im_requested == 1
    assert pm.next_action("input_monitoring") == "open_settings"
    pm.request("input_monitoring")
    assert nat.im_requested == 1

def test_next_action_granted_is_granted():
    pm = mp.PermissionManager(native=_FakeNative(ax=True, im=True))
    assert pm.next_action("accessibility") == "granted"
    assert pm.next_action("input_monitoring") == "granted"


# --- Task 11: System Settings deep-links ---
def test_settings_url_for_each_perm():
    assert mp.settings_url("accessibility").endswith("Privacy_Accessibility")
    assert mp.settings_url("input_monitoring").endswith("Privacy_ListenEvent")
    assert mp.settings_url("accessibility").startswith("x-apple.systempreferences:")

def test_settings_url_fallback_for_unknown():
    assert mp.settings_url("nonsense") == mp.SETTINGS_PRIVACY_ROOT
