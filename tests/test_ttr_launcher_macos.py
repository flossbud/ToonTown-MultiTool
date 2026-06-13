"""macOS TTRLauncher: spawns the nested .app binary with cwd=data dir, and the
trust guard keys on the data dir (not the binary's Contents/MacOS parent).
sys.platform pinned darwin (project_platform_branch_breaks_unpinned_tests)."""
import os
import sys
import threading

from PySide6.QtWidgets import QApplication

from services import ttr_launcher


def _qapp():
    return QApplication.instance() or QApplication([])


class _Proc:
    pid = 4242
    def wait(self):
        return 0


def _make_nested(data_dir):
    nested = data_dir / "Toontown Rewritten.app" / "Contents" / "MacOS"
    nested.mkdir(parents=True)
    binary = nested / "TTREngine"
    binary.write_bytes(b"")
    os.chmod(binary, 0o755)
    return binary


def test_darwin_launch_spawns_nested_bundle_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _qapp()
    data_dir = tmp_path / "Toontown Rewritten"
    binary = _make_nested(data_dir)

    monkeypatch.setattr(ttr_launcher, "in_flatpak", lambda: False, raising=False)
    monkeypatch.setattr(ttr_launcher, "_is_trusted_engine_path", lambda *_: True)

    captured = {}
    spawned = threading.Event()

    def fake_host_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        spawned.set()
        return _Proc()

    monkeypatch.setattr(ttr_launcher, "host_popen", fake_host_popen)

    launcher = ttr_launcher.TTRLauncher()
    launcher.launch("gs", "ck", str(data_dir))

    assert spawned.wait(timeout=2.0), "darwin TTR launch did not spawn"
    assert captured["cmd"] == [str(binary)]
    assert captured["kwargs"]["cwd"] == str(data_dir)
    assert captured["kwargs"]["env"]["TTR_PLAYCOOKIE"] == "ck"
    assert captured["kwargs"]["env"]["TTR_GAMESERVER"] == "gs"
    assert "ck" not in " ".join(captured["cmd"])


def test_darwin_trust_guard_keys_on_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "Toontown Rewritten"
    binary = _make_nested(data_dir)
    monkeypatch.setattr(
        ttr_launcher, "_TRUSTED_ENGINE_DIRS", {os.path.realpath(str(data_dir))})
    # trusted: binary nested under the trusted data dir
    assert ttr_launcher._is_trusted_engine_path(str(binary), str(data_dir)) is True
    # untrusted: a different data dir, not in the set and no approved-custom
    other = tmp_path / "Other"
    other_bin = _make_nested(other)
    assert ttr_launcher._is_trusted_engine_path(str(other_bin), str(other)) is False
