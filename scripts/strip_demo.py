"""Put float strips on existing windows, without the rest of the app.

    python scripts/strip_demo.py --wid 0x2400007 [--wid ...] [--style flat]

Each --wid is a window id as the platform names it (X11 XID, HWND). The
strips follow those windows the way they will follow game windows; clicking
a block changes that strip's own demo state. Prints the [Strips] stamp, then
`STRIP surface <wid> <strip window id>`, `STRIP place <wid> x y w h`,
`STRIP hide <wid>` and `STRIP click <wid> <block> <n>`.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer                        # noqa: E402
from PySide6.QtWidgets import QApplication               # noqa: E402

from utils.strips import layout as L                     # noqa: E402
from utils.strips.follow import StripFollower            # noqa: E402
from utils.strips.model import StripModel                # noqa: E402

DEMO = [
    StripModel(name="Flossbud", accent="#4a8fe7", species="rabbit", home=True),
    StripModel(name="Hector", accent="#e74a4a", species="dog", active=2,
               click_sync=False),
    StripModel(name="Moe", accent="#e7894a", species="cat", game="cc", active=2,
               keep_alive=False, click_sync=None),
    StripModel(name="Linux", accent="#56c856", species="duck", enabled=False),
]


def say(*parts) -> None:
    print(*parts, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wid", action="append", required=True,
                    help="window id (decimal or 0x hex); repeat for more strips")
    ap.add_argument("--style", default="neon", choices=("neon", "flat"))
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let Python run its signal handlers while Qt's loop is idle.
    pulse = QTimer()
    pulse.timeout.connect(lambda: None)
    pulse.start(200)

    follower = StripFollower(style=args.style)

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

    def on_click(wid: str, surface, kind: str, number: int) -> None:
        say("STRIP click", wid, kind, number)
        m = surface.strip.model()
        if kind == L.KEYSET:
            m = m.with_(active=number)
        elif kind == L.ENABLE:
            m = m.with_(enabled=not m.enabled)
        elif kind == L.KEEP_ALIVE:
            m = m.with_(keep_alive=not m.keep_alive)
        elif kind == L.CLICK_SYNC:
            m = m.with_(click_sync=not m.click_sync)
        elif kind == L.ADD and len(m.keysets) < 8:
            m = m.with_(keysets=m.keysets + (max(m.keysets) + 1,),
                        show_add=len(m.keysets) + 1 < 8)
        elif kind == L.HOME:
            m = m.with_(home_open=not m.home_open)
        surface.set_model(m)

    for i, raw in enumerate(args.wid):
        wid = str(int(raw, 0))
        surface = follower.add(wid)
        surface.set_model(DEMO[i % len(DEMO)])
        surface.strip.clicked.connect(
            lambda kind, n, wid=wid, s=surface: on_click(wid, s, kind, n))
        surface.strip.context_requested.connect(
            lambda kind, n, wid=wid: say("STRIP menu", wid, kind, n))
        say("STRIP surface", wid, int(surface.winId()))
    follower.start()
    code = app.exec()
    follower.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
