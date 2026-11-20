"""Render the in-app update surfaces off screen: the header chip in each of
its variants, the update sheet in each state, and What's new.

    python scripts/update_sheet_render.py OUTDIR [--theme dark|light|both] [--scale 2]

The real LaunchpadHeader and UpdateSheetHost in an 880 x 860 stand-in window,
driven by a real UpdateFlow with a stand-in downloader. A construction check
to hold beside the design's frames B1 to B4 and C3.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WINDOW_W, WINDOW_H = 880, 860


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    out = args[0]
    theme = "both"
    scale = 1
    if "--theme" in sys.argv:
        theme = sys.argv[sys.argv.index("--theme") + 1]
    if "--scale" in sys.argv:
        scale = int(sys.argv[sys.argv.index("--scale") + 1])
        args = [a for a in args if a != str(scale)]
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    os.makedirs(out, exist_ok=True)

    from PySide6.QtCore import QObject, QRect, Signal
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])

    from utils import release_highlights, update_flow
    from utils.install_method import InstallMethod
    from utils.rollcall import motion
    from utils.widgets.launchpad.header import HEADER_H, LaunchpadHeader
    from utils.widgets.launchpad.update_sheet import UpdateSheetHost

    motion.set_now(0)

    class Settings:
        def __init__(self):
            self.settings = {}
            self.loaded_keys = frozenset({"theme"})

        def get(self, key, default=None):
            return self.settings.get(key, default)

        def set(self, key, value):
            self.settings[key] = value

    class Downloader(QObject):
        progress = Signal(int, int)
        finished = Signal(str)
        failed = Signal(str)

        def start(self, _asset):
            return True

        def shutdown(self):
            pass

    class StandIn(QWidget):
        def __init__(self, is_dark: bool):
            super().__init__()
            self.is_dark = is_dark
            self.resize(WINDOW_W, WINDOW_H)
            self.header = LaunchpadHeader(self)
            self.header.setGeometry(0, 0, WINDOW_W, HEADER_H)
            self.header.apply_theme(is_dark, QColor("#bbbbbb" if is_dark else "#334155"))
            self.header.setStyleSheet(
                "QFrame#app_header { background: %s; }" % ("#111111" if is_dark else "#e8ecf1"))
            self.sheet = UpdateSheetHost(self, top=HEADER_H)

        def paintEvent(self, _event):
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#1a1a1a" if self.is_dark else "#f8fafc"))
            stripes = ([QColor("#2a4f8a"), QColor("#c0803a")] if self.is_dark
                       else [QColor("#9cc0f0"), QColor("#f2c38c")])
            for i, x in enumerate(range(0, self.width(), 60)):
                p.fillRect(QRect(x, 150, 40, 420), stripes[i % 2])
            p.end()

    notes_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "whats_new.json")
    body = "Notes.\n\n" + release_highlights.body_block(notes_file)
    size = 88_300_000
    info = {
        "tag_name": "v0.8.0-alpha.2", "body": body,
        "html_url": "https://example.invalid/release",
        "assets": [{"name": "ToonTownMultiTool-Setup-v0.8.0-alpha.2.exe", "size": size,
                    "browser_download_url": "https://example.invalid/setup.exe"}],
    }

    def settle(window) -> None:
        for _ in range(60):
            motion.advance(100)
            for part in (window.sheet, window.sheet.stage, window.sheet.stage.copy):
                part._on_tick()
            window.header.update_chip.update()
        app.processEvents()

    def shot(window, name: str) -> None:
        settle(window)
        image = window.grab().toImage()
        image.save(os.path.join(out, f"{name}.png"))
        print(name)

    for is_dark in ([True, False] if theme == "both" else [theme == "dark"]):
        tag = "dark" if is_dark else "light"
        toons = {"up": False}
        window = StandIn(is_dark)
        window.show()
        downloader = Downloader()
        flow = update_flow.UpdateFlow(
            Settings(), install_method=InstallMethod.WINDOWS_INSTALLER,
            local_tag="v0.8.0-alpha.1", downloader=downloader,
            start_update_window=lambda *a, **k: True,
            toons_running=lambda: toons["up"])
        flow.changed.connect(lambda w=window, f=flow: w.header.set_update_chip(f.chip()))
        flow.sheet_requested.connect(
            lambda show, w=window: w.sheet.show_update() if show else w.sheet.hide_sheet())
        window.sheet.set_flow(flow)
        window.header.set_toon_count(0)

        # B2: the chip answers a manual check.
        flow.on_check_started(True)
        shot(window, f"b2-checking-{tag}")
        flow.on_no_update()
        shot(window, f"b2-up-to-date-{tag}")
        flow.on_check_started(True)
        flow.on_check_failed("offline")
        shot(window, f"b2-check-failed-{tag}")

        # B1: offer, download, ready.
        flow.on_check_started(False)
        flow.on_update_available(info)
        shot(window, f"b1-offer-{tag}")
        flow.update_now()
        downloader.progress.emit(int(size * 0.42), size)
        shot(window, f"b1-downloading-{tag}")
        window.sheet.hide_sheet()
        shot(window, f"b1-downloading-hidden-{tag}")
        window.sheet.show_update()

        # B3: the connection dropped.
        flow.received = int(size * 0.37)
        downloader.failed.emit("network")
        shot(window, f"b3-paused-{tag}")
        flow.try_again()
        downloader.progress.emit(size, size)
        flow.installer_path = "C:\\\\Temp\\\\setup.exe"
        downloader.finished.emit("C:\\\\Temp\\\\setup.exe")
        shot(window, f"b1-ready-{tag}")

        # B4: ready, but toons are in game.
        window.sheet.hide_sheet()
        settle(window)
        toons["up"] = True
        window.header.set_toon_count(2)
        window.sheet.show_update()
        shot(window, f"b4-ingame-{tag}")
        window.sheet.hide_sheet()
        shot(window, f"b4-chip-only-{tag}")

        # C3: What's new, three pages, then the chip that reopens it.
        toons["up"] = False
        flow.state = update_flow.NONE
        flow.info = None
        flow.changed.emit()
        notes = release_highlights.from_file(notes_file)
        window.sheet.show_whats_new(notes, "https://example.invalid/release")
        shot(window, f"c3-page1-{tag}")
        window.sheet._go_to_page(1)
        shot(window, f"c3-page2-{tag}")
        window.sheet._go_to_page(2)
        shot(window, f"c3-page3-{tag}")
        window.sheet.hide_sheet()
        flow.mark_whats_new_seen(notes)
        shot(window, f"c3-chip-{tag}")
        window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
