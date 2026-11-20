"""rollcall_main.py, the frozen window's entry point: no error may reach the
bootloader (its message box would block the Setup that waits on the window)."""
import sys
import types

import rollcall_main


def _fake_app(monkeypatch, main):
    module = types.ModuleType("utils.rollcall.app")
    module.main = main
    monkeypatch.setitem(sys.modules, "utils.rollcall.app", module)


def _boom():
    raise RuntimeError("boom")


def test_an_error_before_the_window_was_up_is_could_not_start(tmp_path, monkeypatch):
    _fake_app(monkeypatch, _boom)
    log = tmp_path / "window.log"
    code = rollcall_main.main(["--mode", "install", "--log", str(log),
                               "--ready-file", str(tmp_path / "ready.txt")])
    assert code == rollcall_main.EXIT_COULD_NOT_START
    text = log.read_text(encoding="utf-8")
    assert "before it was up" in text and "RuntimeError: boom" in text


def test_an_error_after_the_window_was_up_is_failed(tmp_path, monkeypatch):
    ready = tmp_path / "ready.txt"
    ready.write_text("up\n", encoding="utf-8")
    _fake_app(monkeypatch, _boom)
    log = tmp_path / "window.log"
    code = rollcall_main.main(["--mode", "update", f"--log={log}", "--ready-file", str(ready)])
    assert code == rollcall_main.EXIT_FAILED
    assert "after it was up" in log.read_text(encoding="utf-8")


def test_the_window_exit_code_passes_through(monkeypatch):
    _fake_app(monkeypatch, lambda: 2)
    assert rollcall_main.main([]) == 2


def test_missing_std_streams_are_replaced(monkeypatch):
    # What a windowed build started by Setup gets: no stdout, no stderr.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    def app_main():
        sys.stdout.write("fine\n")
        sys.stderr.flush()
        return 0

    _fake_app(monkeypatch, app_main)
    try:
        assert rollcall_main.main([]) == 0
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.close()
