import os

# TTMT_NO_VENV_REEXEC must be set BEFORE `import main` anywhere in this
# module (including inside test bodies that import lazily). Without it,
# `main.py` re-execs into ./venv/bin/python on import and pytest hangs.
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_wire_app_lifecycle_shutdowns_window_on_app_quit():
    import main

    callbacks = []

    class _Signal:
        def connect(self, fn):
            callbacks.append(fn)

    class _App:
        aboutToQuit = _Signal()

    calls = []

    class _Window:
        def shutdown(self):
            calls.append("shutdown")

    main._wire_app_lifecycle(_App(), _Window())

    assert len(callbacks) == 1
    callbacks[0]()
    assert calls == ["shutdown"]


def test_main_window_close_requests_qapplication_quit(qapp, monkeypatch, tmp_path):
    import main

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "utils.update_checker.UpdateChecker.check_async",
        lambda self, *, manual: True,
    )

    quit_calls = []
    monkeypatch.setattr(
        main, "_quit_app_after_main_window_close", lambda: quit_calls.append("quit"),
        raising=False,
    )

    window = main.MultiToonTool()
    window.close()

    assert quit_calls == ["quit"]


def test_main_window_shutdown_is_idempotent(qapp, monkeypatch, tmp_path):
    import main

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "utils.update_checker.UpdateChecker.check_async",
        lambda self, *, manual: True,
    )

    window = main.MultiToonTool()
    calls = []

    for label, target in (
        ("hotkey", window.hotkey_manager),
        ("launch", window.launch_tab),
        ("multitoon", window.multitoon_tab),
        ("window", window.window_manager),
        ("update", window.update_checker),
    ):
        method = "stop" if label in {"hotkey", "window"} else "shutdown"
        monkeypatch.setattr(target, method, lambda label=label: calls.append(label))

    window.shutdown()
    window.shutdown()

    assert calls == ["hotkey", "launch", "multitoon", "window", "update"]


def test_about_to_quit_runs_window_shutdown_with_real_qt_signal(
    qapp, monkeypatch, tmp_path
):
    """End-to-end check: exercising the real QApplication.aboutToQuit signal
    actually invokes window.shutdown(). The fake-Signal test above only
    confirms the connect() call shape; this confirms the runtime semantics
    (bound-method connection survives, fires synchronously on app.quit())."""
    import main
    from PySide6.QtCore import QTimer

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "utils.update_checker.UpdateChecker.check_async",
        lambda self, *, manual: True,
    )
    # Replace each manager's shutdown/stop with a no-op so this test
    # doesn't depend on (or hang on) their real implementations. We're
    # testing the wiring, not their behavior.
    window = main.MultiToonTool()
    for target, method in (
        (window.hotkey_manager, "stop"),
        (window.launch_tab, "shutdown"),
        (window.multitoon_tab, "shutdown"),
        (window.window_manager, "stop"),
        (window.update_checker, "shutdown"),
    ):
        monkeypatch.setattr(target, method, lambda: None)

    main._wire_app_lifecycle(qapp, window)
    assert window._shutdown_complete is False

    QTimer.singleShot(0, qapp.quit)
    qapp.exec()

    assert window._shutdown_complete is True
