"""Tests for GamePathRow's CC multi-install handling."""

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
    monkeypatch.setattr(
        "tabs.settings_tab.discover_cc_installs",
        lambda: [_install("only")],
    )
    monkeypatch.setattr(
        "tabs.settings_tab.find_cc_engine_path",
        lambda: "/x/only",
    )
    from tabs.settings_tab import GamePathRow
    from services.cc_login_service import get_cc_engine_executable_name
    row = GamePathRow(
        settings_manager=_SettingsStub(),
        settings_key="cc_engine_dir",
        exe_name_fn=get_cc_engine_executable_name,
        find_path_fn=lambda: "/x/only",
    )
    assert row.needs_pick is False


def test_multi_install_with_no_pick_enters_needs_pick(qapp, monkeypatch):
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "tabs.settings_tab.discover_cc_installs", lambda: installs
    )
    monkeypatch.setattr(
        "tabs.settings_tab.find_cc_engine_path", lambda: "/x/A"
    )
    from tabs.settings_tab import GamePathRow
    from services.cc_login_service import get_cc_engine_executable_name
    row = GamePathRow(
        settings_manager=_SettingsStub(),
        settings_key="cc_engine_dir",
        exe_name_fn=get_cc_engine_executable_name,
        find_path_fn=lambda: "/x/A",
    )
    assert row.needs_pick is True


def test_multi_install_with_matching_signature_does_not_glow(qapp, monkeypatch):
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig = install_signature(installs[0])
    monkeypatch.setattr(
        "tabs.settings_tab.discover_cc_installs", lambda: installs
    )
    monkeypatch.setattr(
        "tabs.settings_tab.find_cc_engine_path", lambda: "/x/A"
    )
    from tabs.settings_tab import GamePathRow
    from services.cc_login_service import get_cc_engine_executable_name
    settings = _SettingsStub({"cc_engine_install_signature": sig,
                               "cc_engine_dir": "/x/A"})
    row = GamePathRow(
        settings_manager=settings,
        settings_key="cc_engine_dir",
        exe_name_fn=get_cc_engine_executable_name,
        find_path_fn=lambda: "/x/A",
    )
    assert row.needs_pick is False


def test_auto_detect_opens_picker_when_needs_pick(qapp, monkeypatch):
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "tabs.settings_tab.discover_cc_installs", lambda: installs
    )
    monkeypatch.setattr(
        "tabs.settings_tab.find_cc_engine_path", lambda: "/x/A"
    )
    monkeypatch.setattr(
        "tabs.settings_tab.os.path.isfile", lambda p: True
    )
    captured = {}

    def _fake_open_picker(row, installs_arg):
        captured["called"] = True
        captured["installs"] = installs_arg
        # Simulate the user picking the second install
        row._apply_picked_install(installs_arg[1])

    monkeypatch.setattr(
        "tabs.settings_tab.GamePathRow._open_picker", _fake_open_picker
    )
    from tabs.settings_tab import GamePathRow
    from services.cc_login_service import get_cc_engine_executable_name
    settings = _SettingsStub()
    row = GamePathRow(
        settings_manager=settings,
        settings_key="cc_engine_dir",
        exe_name_fn=get_cc_engine_executable_name,
        find_path_fn=lambda: "/x/A",
    )
    assert row.needs_pick is True
    row._auto_detect()
    assert captured.get("called") is True
    from services.wine_runtimes import install_signature
    expected_sig = install_signature(installs[1])
    assert settings.get("cc_engine_install_signature") == expected_sig
    assert row.needs_pick is False
    assert settings.get("cc_engine_dir") == os.path.dirname(installs[1].exe_path)


def test_auto_detect_does_not_clobber_signature_when_already_matched(qapp, monkeypatch):
    """Regression test: with multiple installs and a matching stored signature,
    re-clicking Auto-detect must NOT silently change cc_engine_dir/signature.
    Instead it must defer to the picker (giving the user a chance to change
    their mind)."""
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig_b = install_signature(installs[1])
    monkeypatch.setattr(
        "tabs.settings_tab.discover_cc_installs", lambda: installs
    )
    monkeypatch.setattr(
        "tabs.settings_tab.find_cc_engine_path", lambda: "/x/A"
    )
    captured = {"called": False}

    def _fake_open_picker(row, installs_arg):
        captured["called"] = True
        # Simulate the user dismissing the picker (no _apply_picked_install).

    monkeypatch.setattr(
        "tabs.settings_tab.GamePathRow._open_picker", _fake_open_picker
    )
    from tabs.settings_tab import GamePathRow
    from services.cc_login_service import get_cc_engine_executable_name
    settings = _SettingsStub({
        "cc_engine_install_signature": sig_b,
        "cc_engine_dir": "/x/B",
    })
    row = GamePathRow(
        settings_manager=settings,
        settings_key="cc_engine_dir",
        exe_name_fn=get_cc_engine_executable_name,
        find_path_fn=lambda: "/x/A",
    )
    assert row.needs_pick is False
    row._auto_detect()
    # Picker MUST have been called (gives user the chance to change mind).
    assert captured["called"] is True
    # Settings must remain unchanged when picker is dismissed.
    assert settings.get("cc_engine_install_signature") == sig_b
    assert settings.get("cc_engine_dir") == "/x/B"
