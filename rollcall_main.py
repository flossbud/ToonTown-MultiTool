"""Entry point of the Roll Call build (rollcall.exe, rollcall.spec): the
install, update and uninstall windows Setup carries. utils/rollcall/app.py
is the program; this only makes sure a failure to even import it still ends
with the "could not start" exit code, so Setup falls back to its wizard."""
import sys

EXIT_COULD_NOT_START = 3


def main() -> int:
    try:
        from utils.rollcall.app import main as app_main
    except Exception as error:  # noqa: BLE001
        try:
            import os
            import tempfile
            import traceback
            with open(os.path.join(tempfile.gettempdir(), "ttmt-rollcall.log"), "a",
                      encoding="utf-8") as fh:
                fh.write(f"[RollCall] could not load the window: {error}\n"
                         f"{traceback.format_exc()}\n")
        except Exception:  # noqa: BLE001
            pass
        return EXIT_COULD_NOT_START
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
