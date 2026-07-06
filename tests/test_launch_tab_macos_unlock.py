"""Darwin locked/unlock-retry affordance on the launch tab (Milestone 4).

Light UI coverage: with a stub credential manager reporting each darwin
``macos_unlock_state``, ``_build_ui`` must surface the right banner (locked with
an Unlock button for "denied"; a recovery message for "corrupt"; none once
"unlocked"), and the Unlock button must re-run the probe worker.

Offscreen QPA; ``discover_cc_installs`` is stubbed to [] so no modal picker can
block (per the CC launch-gate rule). Non-darwin behavior is unaffected because
the whole affordance is gated on ``sys.platform == "darwin"``.
"""

import sys

import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication

import tabs.launch_tab as launch_tab
from tabs.launch_tab import LaunchTab, MacOSVaultLockedBanner


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tab(monkeypatch, qapp, *, unlock_state, available, pending):
    # Never let a real probe thread run in the test; record calls instead.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: [])
    calls = {"n": 0}
    monkeypatch.setattr(
        LaunchTab, "_start_keyring_probe",
        lambda self: calls.__setitem__("n", calls["n"] + 1),
    )
    cred = MagicMock()
    cred.macos_unlock_state = unlock_state
    cred.keyring_available = available
    cred.keyring_probe_pending = pending
    cred.get_accounts_metadata.return_value = []
    sm = MagicMock(); sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    return tab, calls


def test_denied_shows_locked_banner_with_unlock_button(monkeypatch, qapp):
    tab, _ = _tab(monkeypatch, qapp, unlock_state="denied", available=False, pending=True)
    tab._build_ui()
    banner = tab._keyring_banner
    assert isinstance(banner, MacOSVaultLockedBanner)
    assert banner._mode == "denied"
    assert banner.unlock_button is not None
    assert "locked" in banner.header_label.text().lower()


def test_unlock_button_reruns_probe(monkeypatch, qapp):
    tab, calls = _tab(monkeypatch, qapp, unlock_state="denied", available=False, pending=True)
    tab._build_ui()
    before = calls["n"]
    tab._keyring_banner.unlock_button.click()
    assert calls["n"] == before + 1
    # Button gives feedback + guards against a double-start.
    assert tab._keyring_banner.unlock_button.isEnabled() is False


def test_corrupt_shows_recovery_banner_without_button(monkeypatch, qapp):
    tab, _ = _tab(monkeypatch, qapp, unlock_state="corrupt", available=False, pending=True)
    tab._build_ui()
    banner = tab._keyring_banner
    assert isinstance(banner, MacOSVaultLockedBanner)
    assert banner._mode == "corrupt"
    assert banner.unlock_button is None


def test_unlocked_shows_no_locked_banner(monkeypatch, qapp):
    tab, _ = _tab(monkeypatch, qapp, unlock_state="unlocked", available=True, pending=False)
    tab._build_ui()
    assert not isinstance(tab._keyring_banner, MacOSVaultLockedBanner)
    assert tab._keyring_banner is None


def test_pending_falls_through_to_generic_banner(monkeypatch, qapp):
    # "pending" is not a locked/corrupt state, so the generic keyring-pending
    # banner is used, unchanged.
    from tabs.launch_tab import KeyringPendingBanner
    tab, _ = _tab(monkeypatch, qapp, unlock_state="pending", available=False, pending=True)
    tab._build_ui()
    assert isinstance(tab._keyring_banner, KeyringPendingBanner)


def test_locked_banner_theme_roundtrip(monkeypatch, qapp):
    # refresh_theme calls apply_theme on the banner; it must not raise.
    tab, _ = _tab(monkeypatch, qapp, unlock_state="denied", available=False, pending=True)
    tab._build_ui()
    tab.refresh_theme()
    assert tab._keyring_banner.unlock_button is not None
