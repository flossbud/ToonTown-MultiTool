"""Put float strips on existing windows, without the rest of the app.

    python scripts/strip_demo.py --wid 0x2400007 [--wid ...] [--style flat]

Each --wid is a window id as the platform names it (X11 XID, HWND); up to
four. The windows get the four demo toons of the fake session, in order, and
the real strip controller keeps a strip on each: clicking a block goes
through the session like it will in the app. A window that disappears is
removed from the session, the way the window manager service reports a game
closing.

Prints the [Strips] stamp, then lines an outside check can read:
  STRIP surface <wid> <strip window id>     STRIP home <wid>
  STRIP place <wid> x y w h                 STRIP hide <wid>
  STRIP block <wid> <kind> <n> x y w h dpr  (strip-window-local, on each place)
  STRIP click <wid> <kind> <n>              STRIP menu <wid> <kind> <n>
  STRIP gone <wid>

Reads commands on stdin: `stop`, `start` (the broadcast service),
`features <keep_alive 0|1> <click_sync 0|1>`, `style neon|flat`, `quit`.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, QTimer, Signal            # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from services.toon_session_fake import (DEMO_KEYSET_IDS,      # noqa: E402
                                        FakeToonSession)
from utils.strips.controller import StripController           # noqa: E402
from utils.strips.follow import _platform_geometry            # noqa: E402

GONE_AFTER = 3      # consecutive missing samples before a window counts as closed


def say(*parts) -> None:
    print(*parts, flush=True)


class Stdin(QObject):
    line = Signal(str)

    def start(self) -> None:
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        try:
            for raw in sys.stdin:
                self.line.emit(raw.strip())
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wid", action="append", required=True,
                    help="window id (decimal or 0x hex); repeat for up to four strips")
    ap.add_argument("--style", default="neon", choices=("neon", "flat"))
    args = ap.parse_args()
    wids = [str(int(raw, 0)) for raw in args.wid][:4]

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let Python run its signal handlers while Qt's loop is idle.
    pulse = QTimer()
    pulse.timeout.connect(lambda: None)
    pulse.start(200)

    demo = FakeToonSession.demo().toons()
    session = FakeToonSession(
        [replace(demo[i], window_id=wid, slot=i) for i, wid in enumerate(wids)],
        running=True)
    controller = StripController(session, style=args.style,
                                 keyset_ids=DEMO_KEYSET_IDS)
    follower = controller.follower

    def report_blocks(wid: str) -> None:
        """Block rectangles local to the strip window, plus the pixel ratio,
        so an outside check can aim a pointer at them."""
        surface = follower.surface(wid)
        if surface is None:
            return
        dpr = surface.devicePixelRatioF()
        for b in surface.strip.strip_layout().blocks:
            r = surface.strip.block_rect(b.kind, b.number)
            say("STRIP block", wid, b.kind, b.number, f"{r.x():.1f}", f"{r.y():.1f}",
                f"{r.width():.1f}", f"{r.height():.1f}", f"{dpr:g}")

    def on_place(wid: str, rect) -> None:
        report_blocks(wid)
        say("STRIP place", wid, *rect)

    follower.tracker.place.connect(on_place)
    follower.tracker.hide.connect(lambda wid: say("STRIP hide", wid))
    controller.home_moved.connect(lambda wid: say("STRIP home", wid))
    controller.context_requested.connect(
        lambda wid, kind, n: say("STRIP menu", wid, kind, n))
    controller.start()
    for wid, surface in follower.surfaces().items():
        surface.strip.clicked.connect(
            lambda kind, n, wid=wid: say("STRIP click", wid, kind, n))
        say("STRIP surface", wid, int(surface.winId()))

    # Stand in for the window manager service: a window that stays gone is a
    # game that closed.
    missing: dict[str, int] = {}

    def watch() -> None:
        for toon in session.toons():
            wid = toon.window_id
            if _platform_geometry(wid) is None:
                missing[wid] = missing.get(wid, 0) + 1
                if missing[wid] >= GONE_AFTER:
                    say("STRIP gone", wid)
                    session.remove_toon(wid)
            else:
                missing.pop(wid, None)

    watcher = QTimer()
    watcher.timeout.connect(watch)
    watcher.start(250)

    def command(text: str) -> None:
        words = text.split()
        if not words:
            return
        if words[0] == "stop":
            session.stop()
        elif words[0] == "start":
            session.start()
        elif words[0] == "features" and len(words) == 3:
            session.set_features(keep_alive_available=words[1] == "1",
                                 click_sync_available=words[2] == "1")
        elif words[0] == "style" and len(words) == 2:
            controller.set_style(words[1])
        elif words[0] == "quit":
            app.quit()
        say("STRIP did", text)

    stdin = Stdin()
    stdin.line.connect(command)
    stdin.start()

    code = app.exec()
    controller.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
