"""Tests for launch blocking when multiple CC installs are ambiguous."""

import os
import pytest
from PySide6.QtWidgets import QApplication

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


def test_launch_blocked_when_multi_install_no_pick(qapp, monkeypatch):
    from tabs import launch_tab
    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    blocked = []
    monkeypatch.setattr(
        launch_tab, "_show_multi_install_block",
        lambda parent, settings_manager: blocked.append(True),
    )
    proceed = launch_tab._cc_launch_gate(
        settings_manager=type("S", (), {"get": staticmethod(lambda k, d="": "")})(),
        parent=None,
    )
    assert proceed is False
    assert blocked == [True]


def test_launch_proceeds_when_signature_matches(qapp, monkeypatch):
    from tabs import launch_tab
    from services.wine_runtimes import install_signature
    installs = [_install("A"), _install("B")]
    sig = install_signature(installs[0])
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)

    class _S:
        def get(self, k, d=""):
            return sig if k == "cc_engine_install_signature" else d
        def set(self, k, v): pass

    proceed = launch_tab._cc_launch_gate(settings_manager=_S(), parent=None)
    assert proceed is True


def test_launch_proceeds_and_updates_sig_when_only_one_install(qapp, monkeypatch):
    from tabs import launch_tab
    from services.wine_runtimes import install_signature
    installs = [_install("only")]
    monkeypatch.setattr(launch_tab, "discover_cc_installs", lambda: installs)
    stored = {}

    class _S:
        def get(self, k, d=""):
            return stored.get(k, d)
        def set(self, k, v):
            stored[k] = v

    proceed = launch_tab._cc_launch_gate(settings_manager=_S(), parent=None)
    assert proceed is True
    assert stored["cc_engine_install_signature"] == install_signature(installs[0])
