"""Tests for the CC multi-install handling on the Games page.

Picker-dialog gating moved off `GamePathRow._auto_detect` and onto
`SettingsTab._game_path_auto_detect("cc")` / `_open_cc_install_picker`.
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
    def get(self, key, default=None):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value
    def on_change(self, callback):
        pass


def _install(name, launcher="bottles"):
    from services.wine_runtimes import WineInstall
    return WineInstall(
        exe_path=f"/x/{name}/CorporateClash.exe",
        launcher=launcher,
        prefix_path=f"/x/{name}",
        display_name=f"Bottles · {name}",
        metadata={"bottle_name": name},
    )


def test_single_install_does_not_enter_needs_pick(qapp, monkeypatch):
    """One discovered install → never needs the picker."""
    from tabs import settings_tab
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs",
        lambda: [_install("only")],
    )
    monkeypatch.setattr(
        settings_tab, "find_cc_engine_path", lambda: "/x/only",
    )
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab._cc_needs_pick is False


def test_multi_install_with_no_pick_enters_needs_pick(qapp, monkeypatch):
    """Multiple discovered installs + no stored signature → needs picker."""
    from tabs import settings_tab
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: installs,
    )
    monkeypatch.setattr(
        settings_tab, "find_cc_engine_path", lambda: "/x/A",
    )
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab._cc_needs_pick is True


def test_multi_install_with_matching_signature_does_not_glow(qapp, monkeypatch):
    """Multiple installs but stored signature matches one → no picker needed."""
    from tabs import settings_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig = install_signature(installs[0])
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: installs,
    )
    monkeypatch.setattr(
        settings_tab, "find_cc_engine_path", lambda: "/x/A",
    )
    settings = _SettingsStub({
        "cc_engine_install_signature": sig,
        "cc_engine_dir": "/x/A",
    })
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab._cc_needs_pick is False


def test_auto_detect_opens_picker_when_multi_install(qapp, monkeypatch):
    """Auto-detect with multiple installs delegates to the picker."""
    from tabs import settings_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: installs,
    )
    monkeypatch.setattr(
        settings_tab, "find_cc_engine_path", lambda: "/x/A",
    )
    captured = {}

    def _fake_open_picker(self, installs_arg):
        captured["called"] = True
        captured["installs"] = installs_arg
        # Simulate the user picking the second install.
        picked = installs_arg[1]
        path = os.path.dirname(picked.exe_path)
        self.settings_manager.set("cc_engine_dir", path)
        self.settings_manager.set(
            "cc_engine_install_signature", install_signature(picked),
        )
        self._cc_needs_pick = False

    monkeypatch.setattr(
        settings_tab.SettingsTab, "_open_cc_install_picker", _fake_open_picker,
    )
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab._cc_needs_pick is True
    tab._game_path_auto_detect("cc")
    assert captured.get("called") is True
    expected_sig = install_signature(installs[1])
    assert settings.get("cc_engine_install_signature") == expected_sig
    assert tab._cc_needs_pick is False
    assert settings.get("cc_engine_dir") == os.path.dirname(installs[1].exe_path)


def test_auto_detect_does_not_clobber_signature_when_already_matched(qapp, monkeypatch):
    """Regression: with multiple installs and a matching stored signature,
    re-clicking Auto-detect must NOT silently change cc_engine_dir/signature.
    Instead it must defer to the picker (giving the user a chance to change
    their mind)."""
    from tabs import settings_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig_b = install_signature(installs[1])
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: installs,
    )
    monkeypatch.setattr(
        settings_tab, "find_cc_engine_path", lambda: "/x/A",
    )
    captured = {"called": False}

    def _fake_open_picker(self, installs_arg):
        captured["called"] = True
        # User dismisses the picker — no settings mutation.

    monkeypatch.setattr(
        settings_tab.SettingsTab, "_open_cc_install_picker", _fake_open_picker,
    )
    settings = _SettingsStub({
        "cc_engine_install_signature": sig_b,
        "cc_engine_dir": "/x/B",
    })
    tab = settings_tab.SettingsTab(settings_manager=settings)
    assert tab._cc_needs_pick is False
    tab._game_path_auto_detect("cc")
    # Picker MUST have been called (gives user a chance to change mind).
    assert captured["called"] is True
    # Settings must remain unchanged when picker is dismissed.
    assert settings.get("cc_engine_install_signature") == sig_b
    assert settings.get("cc_engine_dir") == "/x/B"
