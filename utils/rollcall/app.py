"""The Roll Call program: one of the three windows, picked by ``--mode``.

    --mode install|update|uninstall   which window (default install)
    --demo [scenario]                 play it on a timer, touching nothing:
                                      fresh, upgrade, same, newer, running, fail
    --auto                            click the forward path unattended and exit
                                      0 finished / 1 failed / 2 cancelled
    --auto-wipe                       uninstall --auto: also remove user data
    --shots DIR                       save a PNG of the window at every state
    --self-check                      build and paint every window off screen,
                                      exit 0 if the art and the type loaded

Anything else on the command line belongs to the engine (what Setup passes).
Exit 3 means the window could not start at all; Setup then falls back to its
own wizard.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANCELLED = 2
EXIT_COULD_NOT_START = 3

MODES = ("install", "update", "uninstall")
DEMOS = ("fresh", "upgrade", "same", "newer", "running", "fail")


def log(message: str) -> None:
    """Print, and append to ttmt-rollcall.log in the temp directory: the
    frozen build has no console."""
    line = f"[RollCall] {message}"
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        path = os.path.join(tempfile.gettempdir(), "ttmt-rollcall.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _parse(argv):
    parser = argparse.ArgumentParser(prog="rollcall", add_help=True)
    parser.add_argument("--mode", choices=MODES, default="install")
    parser.add_argument("--demo", nargs="?", const="fresh", choices=DEMOS, default=None)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--auto-wipe", action="store_true")
    parser.add_argument("--shots", default="")
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_known_args(argv)


def _os_reduced_motion() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not bool(enabled.value)
    except Exception:  # noqa: BLE001
        pass
    return False


def _demo_engine(mode: str, scenario: str):
    from utils.rollcall.engine import FakeEngine, Flavor, Installed
    flavor = Flavor(version="v0.8.0-alpha.2", build=412, payload_bytes=221_000_000)
    directory = "C:\\Users\\Flossbud\\AppData\\Local\\Programs\\ToonTown MultiTool"
    installed = None
    if mode != "install" or scenario in ("same", "running"):
        installed = Installed("v0.8.0-alpha.2", 412, directory, False)
    if scenario == "upgrade":
        installed = Installed("v0.8.0-alpha.1", 380, directory, False)
    elif scenario == "newer":
        installed = Installed("v0.8.1", 460, directory, False)
    return FakeEngine(
        flavor=flavor, installed=installed, running=scenario == "running",
        fail_at=1 if scenario == "fail" else None,
        duration_ms=6000 if mode != "install" else 7500,
        previous_version="v0.8.0-alpha.1" if mode == "update" else "")


def build_window(mode: str, engine):
    if mode == "update":
        from utils.rollcall.updater import UpdateWindow
        return UpdateWindow(engine)
    if mode == "uninstall":
        from utils.rollcall.uninstaller import UninstallerWindow
        return UninstallerWindow(engine)
    from utils.rollcall.installer import InstallerWindow
    return InstallerWindow(engine)


class Shots:
    """Saves the window as a PNG a moment after every state change."""

    SETTLE_MS = 900

    def __init__(self, window, directory: str):
        from PySide6.QtCore import QTimer
        self._window = window
        self._dir = directory
        self._n = 0
        self._QTimer = QTimer
        os.makedirs(directory, exist_ok=True)
        window.state_changed.connect(self._on_state)
        self._on_state(window.state)

    def _on_state(self, state: str) -> None:
        self._QTimer.singleShot(self.SETTLE_MS, lambda s=state: self.save(s))

    def save(self, label: str) -> str:
        self._n += 1
        path = os.path.join(self._dir, f"{self._n:02d}-{label}.png")
        try:
            self._window.grab().save(path)
        except Exception as error:  # noqa: BLE001
            log(f"shot failed: {error}")
        return path


class AutoDriver:
    """Clicks the forward path so a machine can run the whole window."""

    CLICK_MS = 700
    LINGER_MS = 1800

    def __init__(self, app, window, mode: str, wipe: bool):
        from PySide6.QtCore import QTimer
        self._app = app
        self._window = window
        self._mode = mode
        self._wipe = wipe
        self._QTimer = QTimer
        self.exit_code: int | None = None
        window.state_changed.connect(self._on_state)
        self._on_state(window.state)

    def _button(self, kinds, text: str = ""):
        for control in self._window.stage.copy.controls():
            if getattr(control, "kind", "") in kinds and (not text or control.text() == text):
                return control
        return None

    def _click(self, kinds, text: str = "") -> None:
        def go():
            button = self._button(kinds, text)
            if button is not None and button.isEnabled():
                button.click()
        self._QTimer.singleShot(self.CLICK_MS, go)

    def _exit(self, code: int) -> None:
        self.exit_code = code
        log(f"auto: exit {code}")
        self._QTimer.singleShot(self.LINGER_MS, lambda: self._app.exit(code))

    def _on_state(self, state: str) -> None:
        log(f"state: {state}")
        if state == "fail":
            self._exit(EXIT_FAILED)
        elif state == "undone":
            self._exit(EXIT_CANCELLED)
        elif self._mode == "install":
            if state == "idle":
                self._click(("gold",))
            elif state == "newer":
                self._click(("ghost",), "Install anyway")
            elif state == "maint":
                self._click(("ghost",), "Repair")
            elif state == "busy":
                self._click(("gold",))
            elif state == "done":
                self._exit(EXIT_OK)
        elif self._mode == "uninstall":
            if state == "idle":
                self._window.set_wipe(self._wipe)
                self._click(("red",))
            elif state == "busy":
                self._click(("red",))
            elif state == "done":
                self._exit(EXIT_OK)
        elif self._mode == "update":
            if state == "done":
                self._exit(EXIT_OK)


def self_check(shots: str = "") -> int:
    """Build and paint every window with the timer engine. Proves the frozen
    build carries its art and its type."""
    from PySide6.QtGui import QImage
    from utils.rollcall import fonts, paint
    problems = []
    if not fonts.ensure_loaded():
        problems.append("fonts missing: " + ", ".join(fonts.missing()))
    for index in range(1, 5):
        for pose in ("wave", "bust"):
            if paint.toon_pixmap(index, pose, 64, 1.0).isNull():
                problems.append(f"toon{index}-{pose}.png missing")
    if paint.wordmark(32, 1.0).isNull():
        problems.append("wordmark missing")
    for mode in MODES:
        window = build_window(mode, _demo_engine(mode, "fresh"))
        image: QImage = window.grab().toImage()
        if image.isNull() or image.width() < 100:
            problems.append(f"{mode} window did not paint")
        elif shots:
            os.makedirs(shots, exist_ok=True)
            image.save(os.path.join(shots, f"self-check-{mode}.png"))
        window.close_now()
    if problems:
        for problem in problems:
            log(f"self-check: {problem}")
        return EXIT_COULD_NOT_START
    log("self-check OK")
    return EXIT_OK


def main(argv=None) -> int:
    args, extra = _parse(sys.argv[1:] if argv is None else argv)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv[:1])
        from utils.rollcall import motion
        motion.set_reduced(_os_reduced_motion())
        if args.self_check:
            return self_check(args.shots)
        if args.demo is not None:
            engine, engine_name = _demo_engine(args.mode, args.demo), "fake"
        else:
            from utils.rollcall.engine_inno import build_engine
            engine, engine_name = build_engine(args.mode, extra), "inno"
        window = build_window(args.mode, engine)
    except Exception as error:  # noqa: BLE001
        import traceback
        log(f"could not start: {error}\n{traceback.format_exc()}")
        return EXIT_COULD_NOT_START

    log(f"{args.mode} window, engine={engine_name}, {engine.flavor().version}")
    shots = Shots(window, args.shots) if args.shots else None
    driver = AutoDriver(app, window, args.mode, args.auto_wipe) if args.auto else None
    window.centre_on_screen()
    window.show()
    window.raise_()
    window.activateWindow()
    if args.mode == "update":
        # On screen first; only then is the app asked to go.
        QTimer.singleShot(0, window.start)
    code = app.exec()
    if shots is not None:
        shots.save("exit")
    if driver is not None and driver.exit_code is not None:
        code = driver.exit_code
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
