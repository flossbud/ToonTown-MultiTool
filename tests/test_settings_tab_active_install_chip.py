"""Tests for the CC panel's active-install chip in its subtitle.

The chip is rendered inline in the CC panel's sub_label (rich HTML) via
SettingsTab._refresh_game_path_display when a stored install signature
matches a discovered install. Format is unchanged from the iOS-era row.
"""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _SettingsStub:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, key, default=""):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value
    def on_change(self, callback):
        pass


def _faugus_install():
    from services.wine_runtimes import WineInstall
    return WineInstall(
        exe_path="/home/u/Faugus/corporate-clash/drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/home/u/Faugus/corporate-clash",
        display_name="Faugus · Corporate Clash",
        metadata={"faugus_runner": "Proton", "faugus_install_kind": "flatpak"},
    )


def test_cc_panel_subtitle_includes_faugus_chip_when_signature_matches(qapp, monkeypatch):
    """When the stored signature matches a discovered install, the CC panel
    subtitle renders an inline HTML chip with the launcher label."""
    from tabs import settings_tab
    from services.wine_runtimes import install_signature
    inst = _faugus_install()
    sig = install_signature(inst)
    # Force discovery to return our faugus install (used inside the builder).
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: [inst]
    )
    settings = _SettingsStub({
        "cc_engine_dir": os.path.dirname(inst.exe_path),
        "cc_engine_install_signature": sig,
    })
    tab = settings_tab.SettingsTab(settings_manager=settings)
    # Manually refresh so chip is appended (constructor's first-pass display
    # runs before _cc_installs is populated, by design).
    tab._refresh_game_path_display("cc", os.path.dirname(inst.exe_path))
    sub_text = tab._cc_panel.sub_label.text()
    assert "FAUGUS" in sub_text
    assert "<span" in sub_text
    assert "background-color:" in sub_text
    assert "Faugus · Corporate Clash" in sub_text


def test_cc_panel_subtitle_plain_path_when_no_signature_match(qapp, monkeypatch):
    """No stored signature → plain-path subtitle with no chip span."""
    from tabs import settings_tab
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: []
    )
    settings = _SettingsStub({
        "cc_engine_dir": "/some/path",
    })
    tab = settings_tab.SettingsTab(settings_manager=settings)
    tab._refresh_game_path_display("cc", "/some/path")
    sub_text = tab._cc_panel.sub_label.text()
    assert "<span" not in sub_text
    assert "FAUGUS" not in sub_text
    assert "/some/path" in sub_text or "~/some/path" in sub_text


def test_ttr_panel_subtitle_unaffected(qapp, monkeypatch):
    """The CC-only chip enrichment must not run for the TTR panel."""
    from tabs import settings_tab
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: []
    )
    settings = _SettingsStub({"ttr_engine_dir": "/ttr/path"})
    tab = settings_tab.SettingsTab(settings_manager=settings)
    tab._refresh_game_path_display("ttr", "/ttr/path")
    sub_text = tab._ttr_panel.sub_label.text()
    assert "<span" not in sub_text
    assert "FAUGUS" not in sub_text
