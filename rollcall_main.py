"""Entry point of the Roll Call build (rollcall.exe, rollcall.spec): the
install, update and uninstall windows Setup carries. utils/rollcall/app.py
is the program; this only makes sure that no error ever reaches the
PyInstaller bootloader. In a windowed build an uncaught exception shows a
message box (with or without the traceback), and Setup, which waits for this
process, would wait behind it until the player clicked OK. Instead the error
goes to the window log and the exit code tells Setup what happened:
"could not start" (Setup falls back to its wizard) if the window never came
up, "failed" if it did."""
import os
import sys

EXIT_FAILED = 1
EXIT_COULD_NOT_START = 3


def _streams() -> None:
    # A windowed build started without std handles (Setup starts it so) has
    # sys.stdout and sys.stderr set to None: a write to either would raise.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def _flag(name: str, argv) -> str:
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return ""


def _log(what: str, argv) -> None:
    try:
        import tempfile
        import time
        import traceback
        path = _flag("--log", argv) or os.path.join(tempfile.gettempdir(), "ttmt-rollcall.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [RollCall] {what}\n"
                     f"{traceback.format_exc()}\n")
    except Exception:  # noqa: BLE001
        pass


def _window_was_up(argv) -> bool:
    path = _flag("--ready-file", argv)
    if not path:
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() == "up"
    except OSError:
        return False


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _streams()
    try:
        from utils.rollcall.app import main as app_main
    except Exception as error:  # noqa: BLE001
        _log(f"could not load the window: {error}", argv)
        return EXIT_COULD_NOT_START
    try:
        return app_main()
    except Exception as error:  # noqa: BLE001
        up = _window_was_up(argv)
        _log(f"the window stopped on an error ({'after' if up else 'before'} it was up): "
             f"{error}", argv)
        return EXIT_FAILED if up else EXIT_COULD_NOT_START


if __name__ == "__main__":
    sys.exit(main())
