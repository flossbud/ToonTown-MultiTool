"""Tests for cc_launcher._is_trusted."""

from services.wine_runtimes import WineInstall
from services.cc_launcher import _is_trusted


class _SettingsStub:
    def __init__(self, d=None):
        self._d = d or {}
    def get(self, key, default=None):
        return self._d.get(key, default)


def _mk(launcher, exe_path, prefix=None):
    return WineInstall(
        exe_path=exe_path,
        launcher=launcher,
        prefix_path=prefix,
        display_name="x",
        metadata={},
    )


def test_bottles_install_auto_trusted():
    assert _is_trusted(_mk("bottles", "/x", "/p"), _SettingsStub()) is True


def test_lutris_install_auto_trusted():
    assert _is_trusted(_mk("lutris", "/x", "/p"), _SettingsStub()) is True


def test_steam_proton_install_auto_trusted():
    assert _is_trusted(_mk("steam-proton", "/x", "/p"), _SettingsStub()) is True


def test_wine_install_auto_trusted():
    assert _is_trusted(_mk("wine", "/x", "/p"), _SettingsStub()) is True


def test_native_install_trusted_when_in_search_path(tmp_path, monkeypatch):
    from services import cc_launcher as ccl_module
    install_dir = tmp_path / "Corporate Clash"
    install_dir.mkdir()
    exe = install_dir / "CorporateClash.exe"
    exe.write_text("")
    # Patch the in-launcher binding (the import created a separate name).
    monkeypatch.setattr(
        ccl_module, "CC_ENGINE_SEARCH_PATHS",
        [str(install_dir)],
    )
    assert _is_trusted(_mk("native", str(exe)), _SettingsStub()) is True


def test_native_install_untrusted_when_not_in_search_path(tmp_path):
    exe = tmp_path / "random/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert _is_trusted(_mk("native", str(exe)), _SettingsStub()) is False


def test_native_install_trusted_when_approved_custom(tmp_path):
    exe = tmp_path / "custom/CorporateClash.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    settings = _SettingsStub(
        {"cc_engine_dir_approved_custom_dir": str(tmp_path / "custom")}
    )
    assert _is_trusted(_mk("native", str(exe)), settings) is True
