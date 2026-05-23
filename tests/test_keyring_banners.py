"""KeyringPendingBanner + KeyringWarningBanner visual structure."""
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
    """Banner is styled by __init__ via apply_theme(dark default) — caller
    no longer has to refresh_theme before the banner reads correctly."""
    from tabs.launch_tab import KeyringPendingBanner
    c = get_theme_colors(True)
    banner = KeyringPendingBanner()
    qss = banner.styleSheet()
    assert c["bg_card"] in qss
    assert c["border_card"] in qss
    assert "border-left: 3px" in qss
    assert c["accent_blue"] in qss
    # Regression guards: no saturated bg literal.
    assert "#1e1e2e" not in qss
    assert "#3D2800" not in qss


def test_warning_banner_styled_on_construction(qapp):
    from tabs.launch_tab import KeyringWarningBanner
    c = get_theme_colors(True)
    banner = KeyringWarningBanner(_fake_cred_manager())
    qss = banner.styleSheet()
    assert c["bg_card"] in qss
    assert c["border_card"] in qss
    assert "border-left: 3px" in qss
    assert c["accent_orange_border"] in qss
    assert "#3D2800" not in qss


def test_pending_banner_apply_theme_swaps_to_light(qapp):
    from tabs.launch_tab import KeyringPendingBanner
    light = get_theme_colors(False)
    banner = KeyringPendingBanner()
    banner.apply_theme(light)
    qss = banner.styleSheet()
    assert light["bg_card"] in qss


def test_warning_banner_apply_theme_swaps_to_light(qapp):
    from tabs.launch_tab import KeyringWarningBanner
    light = get_theme_colors(False)
    banner = KeyringWarningBanner(_fake_cred_manager())
    banner.apply_theme(light)
    qss = banner.styleSheet()
    assert light["bg_card"] in qss


def test_warning_banner_fix_label_uses_text_secondary(qapp):
    """The 'how to fix' instructions stay legible with text_secondary
    rather than the dimmer text_muted - spec was updated to match."""
    from tabs.launch_tab import KeyringWarningBanner
    c = get_theme_colors(True)
    banner = KeyringWarningBanner(_fake_cred_manager())
    qss = banner.fix_label.styleSheet()
    assert c["text_secondary"] in qss
