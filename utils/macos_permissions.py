"""macOS TCC permission onboarding: install-location classification + the
Accessibility/Input-Monitoring status+request aggregator + System Settings
deep-links. Pure functions are host-testable; the native (PyObjC/Quartz) calls
are lazy + injectable (so this module imports on any platform)."""
from __future__ import annotations
import os


def classify_location(bundle_path: str) -> str:
    """'ok' | 'translocated' | 'dmg' | 'downloads' | 'other' for an .app path.
    TCC grants bind to an unstable identity unless the app runs from a stable
    location, so onboarding must NOT request permissions unless this is 'ok'."""
    p = os.path.realpath(bundle_path)
    low = p.lower()
    if "/apptranslocation/" in low or "/private/var/folders/" in low:
        return "translocated"
    if p.startswith("/Volumes/"):
        return "dmg"
    if low.startswith(os.path.expanduser("~/downloads").lower()):
        return "downloads"
    if p.startswith("/Applications/") or p.startswith(
            os.path.expanduser("~/Applications/")):
        return "ok"
    return "other"


def is_install_location_ok(bundle_path: str) -> bool:
    return classify_location(bundle_path) == "ok"


def _default_native():
    """Lazy real backend. Accessibility via AXIsProcessTrustedWithOptions;
    Input Monitoring via CGPreflight/CGRequestListenEventAccess. Imports inside
    so the module loads on any host."""
    class _Native:
        def accessibility_granted(self):
            try:
                from ApplicationServices import (
                    AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
                return bool(AXIsProcessTrustedWithOptions(
                    {kAXTrustedCheckOptionPrompt: False}))
            except Exception:
                return False
        def request_accessibility(self):
            try:
                from ApplicationServices import (
                    AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
                AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
            except Exception:
                pass
        def input_monitoring_granted(self):
            try:
                import Quartz
                fn = getattr(Quartz, "CGPreflightListenEventAccess", None)
                return bool(fn()) if fn else True
            except Exception:
                return False
        def request_input_monitoring(self):
            try:
                import Quartz
                fn = getattr(Quartz, "CGRequestListenEventAccess", None)
                if fn:
                    fn()
            except Exception:
                pass
    return _Native()


class PermissionManager:
    """Tracks Accessibility + Input Monitoring status and the one-shot request
    transition. UI-agnostic + native-injectable for tests."""
    PERMS = ("accessibility", "input_monitoring")

    # Whether a perm's native check is trustworthy IN-PROCESS right after we
    # fire its OS request this session. Accessibility's AXIsProcessTrusted
    # reflects durable trust live, so True. Input Monitoring's
    # CGPreflightListenEventAccess can read a FALSE True in the same process
    # after CGRequestListenEventAccess (it reports current-process effective
    # access, which diverges from the durable, Settings-visible grant), so
    # False: only a fresh-process preflight (next launch) is authoritative.
    _RELIABLE_INPROCESS_RECHECK = {"accessibility": True, "input_monitoring": False}

    def __init__(self, native=None):
        self._n = native if native is not None else _default_native()
        self._requested = set()

    def _granted(self, perm):
        return (self._n.accessibility_granted() if perm == "accessibility"
                else self._n.input_monitoring_granted())

    def _confirmed_granted(self, perm):
        """True only when the native check can be TRUSTED. Once we've fired the
        request this session for a perm whose in-process recheck is unreliable
        (Input Monitoring), the check is not authoritative until the app is
        relaunched, so report not-granted and route the user to Settings."""
        if perm in self._requested and not self._RELIABLE_INPROCESS_RECHECK[perm]:
            return False
        return bool(self._granted(perm))

    def status(self):
        return {p: self._confirmed_granted(p) for p in self.PERMS}

    def all_granted(self):
        return all(self.status().values())

    def next_action(self, perm):
        """'granted' | 'request' (prompt not yet fired) | 'open_settings'."""
        if self._confirmed_granted(perm):
            return "granted"
        return "open_settings" if perm in self._requested else "request"

    def request(self, perm):
        """Fire the one-shot OS prompt exactly once; afterwards route to
        Settings (the prompt does not re-show)."""
        if perm in self._requested or self._granted(perm):
            return
        self._requested.add(perm)
        (self._n.request_accessibility if perm == "accessibility"
         else self._n.request_input_monitoring)()


SETTINGS_PRIVACY_ROOT = "x-apple.systempreferences:com.apple.preference.security?Privacy"
_SETTINGS_ANCHORS = {
    "accessibility": SETTINGS_PRIVACY_ROOT + "_Accessibility",
    "input_monitoring": SETTINGS_PRIVACY_ROOT + "_ListenEvent",
}


def settings_url(perm: str) -> str:
    """Deep-link to the exact privacy pane; unknown perm -> the general
    Privacy & Security root (anchors are version-fragile, so callers that fail
    to open the specific pane should also fall back to the root)."""
    return _SETTINGS_ANCHORS.get(perm, SETTINGS_PRIVACY_ROOT)


def open_settings(perm: str) -> None:
    """Open the privacy pane via `open`; never raises."""
    import subprocess
    try:
        subprocess.Popen(["open", settings_url(perm)])
    except Exception:
        try:
            subprocess.Popen(["open", SETTINGS_PRIVACY_ROOT])
        except Exception:
            pass
