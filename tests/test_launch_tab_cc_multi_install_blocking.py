"""Tests for the CC launch gate's multi-install inline picker flow."""

import os
import pytest
from PySide6.QtWidgets import QApplication, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _install(name, launcher="bottles"):
    from services.wine_runtimes import WineInstall
    return WineInstall(
        exe_path=f"/x/{name}/CorporateClash.exe",
        launcher=launcher,
        prefix_path=f"/x/{name}",
        display_name=f"Bottles · {name}",
        metadata={"bottle_name": name},
    )


class _SettingsStub:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, key, default=""):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value


def test_launch_blocked_when_picker_cancelled(qapp, monkeypatch):
    """User declines the inline picker — gate returns False."""
    from tabs import launch_tab
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    monkeypatch.setattr(
        launch_tab, "_prompt_inline_picker",
        lambda parent, installs, sm: False,
    )
    proceed = launch_tab._cc_launch_gate(
        settings_manager=_SettingsStub(), parent=None,
    )
    assert proceed is False


def test_launch_proceeds_when_picker_accepted(qapp, monkeypatch):
    """User picks an install in the inline picker — gate returns True."""
    from tabs import launch_tab
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    monkeypatch.setattr(
        launch_tab, "_prompt_inline_picker",
        lambda parent, installs, sm: True,
    )
    proceed = launch_tab._cc_launch_gate(
        settings_manager=_SettingsStub(), parent=None,
    )
    assert proceed is True


def test_prompt_inline_picker_persists_signature_on_accept(qapp, monkeypatch):
    """When the picker accepts, the gate helper writes cc_engine_dir +
    signature + clears approved_custom_dir."""
    from tabs import launch_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]

    class _FakeDialog:
        Accepted = QDialog.Accepted
        def __init__(self, installs, parent=None, active_signature=None):
            self._installs = installs
        def exec(self):
            return QDialog.Accepted
        def selected_install(self):
            return self._installs[1]

    monkeypatch.setattr(launch_tab, "CCInstallPickerDialog", _FakeDialog)
    settings = _SettingsStub()
    result = launch_tab._prompt_inline_picker(None, installs, settings)
    assert result is True
    assert settings.get("cc_engine_dir") == "/x/B"
    assert settings.get("cc_engine_install_signature") == install_signature(installs[1])
    assert settings.get("cc_engine_dir_approved_custom_dir") == ""


def test_prompt_inline_picker_returns_false_on_reject(qapp, monkeypatch):
    from tabs import launch_tab
    installs = [_install("A"), _install("B")]

    class _FakeDialog:
        Accepted = QDialog.Accepted
        def __init__(self, installs, parent=None, active_signature=None):
            pass
        def exec(self):
            return QDialog.Rejected
        def selected_install(self):
            return None

    monkeypatch.setattr(launch_tab, "CCInstallPickerDialog", _FakeDialog)
    settings = _SettingsStub()
    assert launch_tab._prompt_inline_picker(None, installs, settings) is False
    assert settings.get("cc_engine_dir", None) is None


def test_launch_proceeds_when_signature_matches(qapp, monkeypatch):
    """Stored signature matches one of the installs — no picker, no block."""
    from tabs import launch_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig = install_signature(installs[0])
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    proceed = launch_tab._cc_launch_gate(
        settings_manager=_SettingsStub({"cc_engine_install_signature": sig}),
        parent=None,
    )
    assert proceed is True


def test_launch_proceeds_and_updates_sig_when_only_one_install(qapp, monkeypatch):
    from tabs import launch_tab
    from services.wine_runtimes import install_signature
    installs = [_install("only")]
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    settings = _SettingsStub()
    proceed = launch_tab._cc_launch_gate(settings_manager=settings, parent=None)
    assert proceed is True
    assert settings.get("cc_engine_install_signature") == install_signature(installs[0])
