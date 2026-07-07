"""KeyringPendingBanner + KeyringWarningBanner + MacOSVaultLockedBanner
visual structure: tinted-card frames (Launch v2), no left-border stripe."""
from unittest.mock import MagicMock
import pytest
from PySide6.QtWidgets import QApplication
from utils.theme_manager import get_theme_colors


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_cred_manager():
    """KeyringWarningBanner needs a cred_manager with _legacy_fallback_deleted."""
    cm = MagicMock()
    cm._legacy_fallback_deleted = False
    return cm


def test_pending_banner_styled_on_construction(qapp):
    """Banner is styled by __init__ via apply_theme(dark default) - caller
    no longer has to refresh_theme before the banner reads correctly."""
    from tabs.launch_tab import KeyringPendingBanner, INFO_BLUE

    banner = KeyringPendingBanner()
    qss = banner.styleSheet()
    assert "border-left" not in qss.lower()
    assert "background:" in qss
    assert "border-radius: 12px" in qss
    # Tinted-card wash is built from the fixed info-blue accent, not the
    # theme dict's own (desaturated) accent_blue token.
    assert "0, 119, 255" in qss  # rgba() channels for #0077ff
    # Regression guards: no legacy neutral-card literal.
    assert "#1e1e2e" not in qss
    assert "#3D2800" not in qss


def test_warning_banner_styled_on_construction(qapp):
    from tabs.launch_tab import KeyringWarningBanner

    banner = KeyringWarningBanner(_fake_cred_manager())
    qss = banner.styleSheet()
    assert "border-left" not in qss.lower()
    assert "border-radius: 12px" in qss
    assert "255, 149, 0" in qss  # rgba() channels for #ff9500
    assert "#3D2800" not in qss


def test_macos_vault_banner_styled_on_construction(qapp):
    from tabs.launch_tab import MacOSVaultLockedBanner

    banner = MacOSVaultLockedBanner("denied", lambda: None)
    qss = banner.styleSheet()
    assert "border-left" not in qss.lower()
    assert "border-radius: 12px" in qss
    assert "255, 149, 0" in qss  # warning-orange accent, both modes


def test_pending_banner_apply_theme_swaps_to_light(qapp):
    from tabs.launch_tab import KeyringPendingBanner

    light = get_theme_colors(False)
    banner = KeyringPendingBanner()
    dark_qss = banner.styleSheet()
    banner.apply_theme(light)
    light_qss = banner.styleSheet()
    assert light_qss != dark_qss
    assert "border-left" not in light_qss.lower()


def test_warning_banner_apply_theme_swaps_to_light(qapp):
    from tabs.launch_tab import KeyringWarningBanner

    light = get_theme_colors(False)
    banner = KeyringWarningBanner(_fake_cred_manager())
    dark_qss = banner.styleSheet()
    banner.apply_theme(light)
    light_qss = banner.styleSheet()
    assert light_qss != dark_qss
    assert "border-left" not in light_qss.lower()


def test_warning_banner_fix_label_uses_text_secondary(qapp):
    """The 'how to fix' instructions stay legible with text_secondary
    rather than the dimmer text_muted - spec was updated to match."""
    from tabs.launch_tab import KeyringWarningBanner
    c = get_theme_colors(True)
    banner = KeyringWarningBanner(_fake_cred_manager())
    qss = banner.fix_label.styleSheet()
    assert c["text_secondary"] in qss


def test_pending_banner_no_left_border_stripe(qapp):
    from tabs.launch_tab import KeyringPendingBanner
    b = KeyringPendingBanner()
    assert "border-left" not in b.styleSheet().lower()


def test_warning_banner_no_left_border_stripe(qapp):
    from tabs.launch_tab import KeyringWarningBanner
    b = KeyringWarningBanner(MagicMock())
    assert "border-left" not in b.styleSheet().lower()


def test_macos_vault_banner_no_left_border_stripe(qapp):
    from tabs.launch_tab import MacOSVaultLockedBanner
    b = MacOSVaultLockedBanner("locked", lambda: None)
    assert "border-left" not in b.styleSheet().lower()
