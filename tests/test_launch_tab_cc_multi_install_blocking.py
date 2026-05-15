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


def test_switch_to_cc_settings_calls_nav_select_direct(qapp):
    """Direct hit: parent itself exposes nav_select."""
    from tabs.launch_tab import _switch_to_cc_settings

    class _Parent:
        def __init__(self):
            self.calls = []
        def nav_select(self, idx):
            self.calls.append(idx)

    p = _Parent()
    _switch_to_cc_settings(p)
    assert p.calls == [3]


def test_switch_to_cc_settings_walks_parent_tree(qapp):
    """Walks up parent() chain until it finds nav_select."""
    from tabs.launch_tab import _switch_to_cc_settings

    class _Root:
        def __init__(self):
            self.calls = []
        def nav_select(self, idx):
            self.calls.append(idx)
        def parent(self):
            return None

    class _Child:
        def __init__(self, root):
            self._root = root
        def parent(self):
            return self._root

    root = _Root()
    child = _Child(root)
    _switch_to_cc_settings(child)
    assert root.calls == [3]


def test_switch_to_cc_settings_no_nav_select_no_crash(qapp):
    """Graceful no-op if nothing in the tree exposes nav_select."""
    from tabs.launch_tab import _switch_to_cc_settings

    class _Orphan:
        def parent(self):
            return None

    # Should not raise.
    _switch_to_cc_settings(_Orphan())
    _switch_to_cc_settings(None)
