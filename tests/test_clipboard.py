import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils import clipboard


class _Result:
    returncode = 0


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_copy_text_sets_qt_clipboard(qapp, monkeypatch):
    monkeypatch.setattr(clipboard, "in_flatpak", lambda: False)

    assert clipboard.copy_text("plain qt copy")

    assert QApplication.clipboard().text() == "plain qt copy"


def test_copy_text_flatpak_sends_host_clipboard_over_stdin(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(clipboard, "in_flatpak", lambda: True)

    def fake_host_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Result()

    monkeypatch.setattr(clipboard, "host_run", fake_host_run)

    assert clipboard.copy_text("secret\nnot-in-argv")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ["sh", "-c"]
    assert "wl-copy" in argv[2]
    assert "secret" not in " ".join(argv)
    assert kwargs["input"] == b"secret\nnot-in-argv"
    assert QApplication.clipboard().text() == "secret\nnot-in-argv"


def test_copy_text_flatpak_host_exception_reports_failure(qapp, monkeypatch):
    # A broken/missing flatpak-spawn must not crash, still sets the Qt
    # clipboard, but reports False: in Flatpak the Qt clipboard is unreliable,
    # so we cannot promise the copy is pasteable.
    monkeypatch.setattr(clipboard, "in_flatpak", lambda: True)

    def fake_host_run(*_args, **_kwargs):
        raise FileNotFoundError("flatpak-spawn")

    monkeypatch.setattr(clipboard, "host_run", fake_host_run)

    assert clipboard.copy_text("qt survives fallback failure") is False
    assert QApplication.clipboard().text() == "qt survives fallback failure"


def test_copy_text_flatpak_host_helper_missing_reports_failure(qapp, monkeypatch):
    # No wl-copy/xclip/xsel on the host -> script exits 127 -> not pasteable.
    monkeypatch.setattr(clipboard, "in_flatpak", lambda: True)

    class _Missing:
        returncode = 127

    monkeypatch.setattr(clipboard, "host_run", lambda *a, **k: _Missing())

    assert clipboard.copy_text("no helper installed") is False


def test_copy_text_flatpak_host_helper_success_reports_true(qapp, monkeypatch):
    monkeypatch.setattr(clipboard, "in_flatpak", lambda: True)
    monkeypatch.setattr(clipboard, "host_run", lambda *a, **k: _Result())

    assert clipboard.copy_text("helper ok") is True
