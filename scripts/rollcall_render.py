"""Render the Roll Call windows' states to PNGs, off screen.

    python scripts/rollcall_render.py <out dir> [--scale 2]

One file per design frame and state (a1-idle, a1-run, a2-customize, ...,
d2-busy), settled: every animation at its end. A construction check to hold
beside the design prototype, not a validation of the real windows.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    out = args[0]
    scale = 2
    if "--scale" in sys.argv:
        scale = float(sys.argv[sys.argv.index("--scale") + 1])
    os.makedirs(out, exist_ok=True)
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    app = QApplication.instance() or QApplication([])

    from utils.rollcall import motion
    from utils.rollcall.engine import Failure, FakeEngine, Flavor, Installed
    from utils.rollcall.installer import InstallerWindow
    from utils.rollcall.uninstaller import UninstallerWindow
    from utils.rollcall.updater import UpdateWindow

    motion.set_now(0)
    flavor = Flavor(version="v0.8.0-alpha.2", build=412, payload_bytes=221_000_000)
    directory = "C:\\Users\\Flossbud\\AppData\\Local\\Programs\\ToonTown MultiTool"
    same = Installed("v0.8.0-alpha.2", 412, directory, False)
    older = Installed("v0.8.0-alpha.1", 380, directory, False)
    newer = Installed("v0.8.1", 460, directory, False)
    failure = Failure(
        step=1, headline="Couldn\u2019t copy the files.",
        body="Windows blocked writing to the install folder. "
             "Anything already copied was removed.",
        detail="Access is denied \u00b7 0x80070005")

    def settle(window) -> None:
        for _ in range(80):
            motion.advance(100)
            for part in (window.stage, window.stage.copy, getattr(window, "panel", None)):
                if part is not None:
                    part._on_tick()
            for name in ("_refresh_run", "_refresh"):
                refresh = getattr(window, name, None)
                if refresh is not None:
                    refresh()
        app.processEvents()

    def shot(window, name: str) -> None:
        settle(window)
        grabbed = window.grab().toImage()
        image = QImage(grabbed.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#2a2f3a"))
        grabbed.setDevicePixelRatio(1.0)
        painter = QPainter(image)
        painter.drawImage(0, 0, grabbed)
        painter.end()
        image.save(os.path.join(out, f"{name}.png"))
        print(name)

    def installer(installed=None, running=False):
        engine = FakeEngine(flavor=flavor, installed=installed, running=running)
        engine._timer.setInterval(10_000_000)      # the harness drives progress by hand
        window = InstallerWindow(engine)
        window.show()
        return window, engine

    # A1: welcome, installing, cancel, done.
    window, engine = installer()
    shot(window, "a1-idle")
    window._on_install()
    engine.step_progress.emit(1, 0.44)
    shot(window, "a1-run")
    window._on_cancel_link()
    shot(window, "a1-ask")
    cancel, engine.cancel = engine.cancel, lambda: None
    window._on_stop()
    shot(window, "a1-stopping")
    engine.cancel = cancel
    engine._timer.stop()
    window._on_cancelled()
    shot(window, "a1-undone")
    window._on_start_over()
    window._on_install()
    engine.step_progress.emit(3, 0.9)
    settle(window)
    engine._timer.stop()
    engine.finished.emit()
    shot(window, "a1-done")

    # A2: Customize, and the Keep-Alive consent block.
    window, engine = installer()
    window._toggle_panel()
    shot(window, "a2-customize")
    window.panel._on_keep_alive()
    shot(window, "a2-consent")
    window.panel._on_accept()
    shot(window, "a2-keep-alive-on")

    # A3: this version is installed. A4: the app is running. A5: a step failed.
    window, engine = installer(installed=same)
    shot(window, "a3-maint")
    window, engine = installer(running=True)
    window._on_install()
    shot(window, "a4-busy")
    window, engine = installer()
    window._on_install()
    engine.step_progress.emit(1, 0.6)
    settle(window)
    engine._timer.stop()
    engine.failed.emit(failure)
    shot(window, "a5-fail")

    # Not drawn in the design: over an older version, and over a newer one.
    window, engine = installer(installed=older)
    shot(window, "a-upgrade")
    window, engine = installer(installed=newer)
    shot(window, "a-newer")

    # C1 and C2.
    def updater():
        engine = FakeEngine(flavor=flavor, installed=older, previous_version="v0.8.0-alpha.1")
        engine._timer.setInterval(10_000_000)
        window = UpdateWindow(engine)
        window.show()
        window.start()
        return window, engine

    window, engine = updater()
    engine.step_progress.emit(0, 0.5)
    shot(window, "c1-closing")
    engine.step_progress.emit(1, 0.55)
    shot(window, "c1-installing")
    engine.step_progress.emit(2, 0.6)
    shot(window, "c1-reopening")
    engine._timer.stop()
    engine.finished.emit()
    shot(window, "c1-done")
    window, engine = updater()
    engine.step_progress.emit(1, 0.5)
    settle(window)
    engine._timer.stop()
    engine.failed.emit(Failure(
        step=1, headline="The update didn\u2019t finish.",
        body="Your previous version is back. Nothing was lost."))
    shot(window, "c2-fail")
    window, engine = updater()
    engine.step_progress.emit(1, 0.5)
    settle(window)
    engine._timer.stop()
    engine.failed.emit(Failure(
        step=1, headline="The update didn\u2019t finish.",
        body="Run the installer again to repair MultiTool.", previous_intact=False))
    shot(window, "c2-fail-not-restored")

    # D1 and D2.
    def uninstaller(running=False):
        engine = FakeEngine(flavor=flavor, installed=same, running=running)
        engine._timer.setInterval(10_000_000)
        window = UninstallerWindow(engine)
        window.show()
        return window, engine

    window, engine = uninstaller()
    shot(window, "d1-idle")
    window._on_uninstall()
    engine.step_progress.emit(1, 0.5)
    shot(window, "d1-run")
    engine._timer.stop()
    engine.finished.emit()
    shot(window, "d1-done")
    window, engine = uninstaller()
    window.set_wipe(True)
    shot(window, "d1-idle-ticked")
    window._on_uninstall()
    engine._timer.stop()
    engine.finished.emit()
    shot(window, "d1-done-wiped")
    window, engine = uninstaller(running=True)
    shot(window, "d2-busy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
