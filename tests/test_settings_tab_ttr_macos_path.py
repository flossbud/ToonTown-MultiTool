"""macOS TTR engine-path validation in Settings: browse/auto-detect for TTR must
route the binary-existence check through engine_binary_path so a data dir whose
nested .app bundle holds TTREngine validates and stores.

The browse test patches settings_tab.engine_binary_path to the macOS nesting
directly (rather than a global sys.platform patch, which would perturb tab
construction), and creates the real nested file so os.path.isfile passes."""
import os

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

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


def _quiet_autodetect(monkeypatch, settings_tab):
    # Keep tab construction deterministic regardless of host. On a machine with
    # TTR actually installed, SettingsTab construction silently auto-detects and
    # pre-stores ttr_engine_dir (via find_engine_path), which would mask what
    # _game_path_browse itself stores; neutralize both games' auto-detect so the
    # tests observe only the action under test.
    monkeypatch.setattr(
        "services.cc_login_service.discover_cc_installs", lambda: [])
    monkeypatch.setattr(settings_tab, "find_cc_engine_path", lambda: None)
    monkeypatch.setattr(settings_tab, "find_engine_path", lambda: None)


def test_browse_validates_macos_data_dir_with_nested_bundle(qapp, tmp_path, monkeypatch):
    from tabs import settings_tab
    _quiet_autodetect(monkeypatch, settings_tab)
    data_dir = tmp_path / "Toontown Rewritten"
    nested = data_dir / "Toontown Rewritten.app" / "Contents" / "MacOS"
    nested.mkdir(parents=True)
    (nested / "TTREngine").write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        settings_tab, "engine_binary_path",
        lambda d: os.path.join(
            d, "Toontown Rewritten.app", "Contents", "MacOS", "TTREngine"),
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(data_dir)),
    )
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    tab._game_path_browse("ttr")
    assert settings.get("ttr_engine_dir") == str(data_dir)


def test_browse_rejects_macos_dir_without_bundle(qapp, tmp_path, monkeypatch):
    from tabs import settings_tab
    _quiet_autodetect(monkeypatch, settings_tab)
    data_dir = tmp_path / "Empty"
    data_dir.mkdir()
    monkeypatch.setattr(
        settings_tab, "engine_binary_path",
        lambda d: os.path.join(
            d, "Toontown Rewritten.app", "Contents", "MacOS", "TTREngine"),
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(data_dir)),
    )
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    tab._game_path_browse("ttr")
    assert settings.get("ttr_engine_dir") is None


def test_auto_detect_stores_ttr_data_dir(qapp, tmp_path, monkeypatch):
    from tabs import settings_tab
    _quiet_autodetect(monkeypatch, settings_tab)
    data_dir = str(tmp_path / "Toontown Rewritten")
    monkeypatch.setattr(settings_tab, "find_engine_path", lambda: data_dir)
    settings = _SettingsStub()
    tab = settings_tab.SettingsTab(settings_manager=settings)
    tab._game_path_auto_detect("ttr")
    assert settings.get("ttr_engine_dir") == data_dir
