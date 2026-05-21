"""Tests that LaunchTab owns a WineConsoleHider and attaches it to each
newly-created CCLauncher."""

import os
import pytest
from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeCCLauncher(QObject):
    game_launched = Signal(int)
    game_exited = Signal(int)
    launch_failed = Signal(str)
    def __init__(self, *a, **kw):
        super().__init__()


def test_launch_tab_constructs_wine_console_hider(qapp, monkeypatch):
    """LaunchTab must expose a `_wine_console_hider` attribute."""
    from tabs import launch_tab
    # Avoid touching real settings/discovery in LaunchTab.__init__.
    monkeypatch.setattr(launch_tab, "CCLauncher", _FakeCCLauncher, raising=False)
    tab = launch_tab.LaunchTab(settings_manager=_StubSettings())
    assert hasattr(tab, "_wine_console_hider")
    from services.wine_console_hider import WineConsoleHider
    assert isinstance(tab._wine_console_hider, WineConsoleHider)


def test_make_launchers_attaches_hider_to_each_new_cc_launcher(qapp, monkeypatch):
    """When _make_launchers spawns a CCLauncher for the CC game, its
    game_launched signal must be wired through the hider."""
    from tabs import launch_tab

    fake = _FakeCCLauncher()
    monkeypatch.setattr(launch_tab, "CCLauncher", lambda *a, **kw: fake, raising=False)

    tab = launch_tab.LaunchTab(settings_manager=_StubSettings())

    # Replace the hider with a recording stub so we can assert attach was called.
    attached = []
    class _RecHider:
        def attach(self, launcher):
            attached.append(launcher)
    tab._wine_console_hider = _RecHider()

    # Invoke the per-section launcher factory; signature is project-internal,
    # so the test calls it with the same shape LaunchTab uses internally.
    tab._make_launchers(game="cc", section_index=0)
    assert attached == [fake], (
        f"expected hider.attach(<the new CCLauncher>) exactly once, got {attached}"
    )


def test_make_launchers_does_not_attach_for_ttr(qapp, monkeypatch):
    """TTR launches must not route through the CC console hider."""
    from tabs import launch_tab

    class _FakeTTRLauncher(QObject):
        game_launched = Signal(int)
        game_exited = Signal(int)
        launch_failed = Signal(str)
        def __init__(self, *a, **kw):
            super().__init__()

    monkeypatch.setattr(launch_tab, "TTRLauncher", lambda *a, **kw: _FakeTTRLauncher(), raising=False)

    tab = launch_tab.LaunchTab(settings_manager=_StubSettings())
    attached = []
    class _RecHider:
        def attach(self, launcher): attached.append(launcher)
    tab._wine_console_hider = _RecHider()

    tab._make_launchers(game="ttr", section_index=0)
    assert attached == []


class _StubSettings:
    def get(self, key, default=None):
        return default
    def set(self, key, value):
        pass
