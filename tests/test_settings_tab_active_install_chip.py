"""Tests for the Settings CC row 'active install' subtitle."""

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


def _faugus_install():
    from services.wine_runtimes import WineInstall
    return WineInstall(
        exe_path="/home/u/Faugus/corporate-clash/drive_c/users/steamuser/AppData/Local/Corporate Clash/CorporateClash.exe",
        launcher="faugus",
        prefix_path="/home/u/Faugus/corporate-clash",
        display_name="Faugus · Corporate Clash",
        metadata={"faugus_runner": "Proton", "faugus_install_kind": "flatpak"},
    )


def test_cc_row_subtitle_includes_faugus_chip_when_signature_matches(qapp, monkeypatch):
    from tabs import settings_tab
    from services.wine_runtimes import install_signature
    inst = _faugus_install()
    sig = install_signature(inst)
    monkeypatch.setattr(
        settings_tab, "discover_cc_installs", lambda: [inst]
    )
    settings = _SettingsStub({
        "cc_engine_dir": os.path.dirname(inst.exe_path),
        "cc_engine_install_signature": sig,
    })
    row = settings_tab.GamePathRow(
        settings, "cc_engine_dir",
        exe_name_fn=lambda: "CorporateClash.exe",
        find_path_fn=lambda: os.path.dirname(inst.exe_path),
        label="Corporate Clash Path",
    )
    text = row.sub_widget.text()
    assert "[FAUGUS]" in text
    assert "Faugus · Corporate Clash" in text


def test_cc_row_subtitle_plain_path_when_no_signature_match(qapp, monkeypatch):
    from tabs import settings_tab
    monkeypatch.setattr(settings_tab, "discover_cc_installs", lambda: [])
    settings = _SettingsStub({
        "cc_engine_dir": "/some/path",
        # no signature stored
    })
    row = settings_tab.GamePathRow(
        settings, "cc_engine_dir",
        exe_name_fn=lambda: "CorporateClash.exe",
        find_path_fn=lambda: "/some/path",
        label="Corporate Clash Path",
    )
    text = row.sub_widget.text()
    assert "[FAUGUS]" not in text
    assert "/some/path" in text or "~/some/path" in text


def test_ttr_row_subtitle_unaffected(qapp, monkeypatch):
    """The CC-only enrichment must not run for the TTR row."""
    from tabs import settings_tab
    monkeypatch.setattr(settings_tab, "discover_cc_installs", lambda: [])
    settings = _SettingsStub({"ttr_engine_dir": "/ttr/path"})
    row = settings_tab.GamePathRow(
        settings, "ttr_engine_dir",
        exe_name_fn=lambda: "TTREngine.exe",
        find_path_fn=lambda: "/ttr/path",
        label="TTR Path",
    )
    text = row.sub_widget.text()
    # No chip; just the path.
    assert "[" not in text or "FAUGUS" not in text
