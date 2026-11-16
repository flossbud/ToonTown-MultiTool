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
  STRIP click <wid> <kind> <n>              STRIP gone <wid>
  STRIP counters <wid> <window id>|hidden
  STRIP popover <wid> <tag> <window id>     STRIP popover-closed <wid> <tag>
  STRIP pill <wid> <index> x y w h dpr <key>  (popover-window-local)
  STRIP zone <wid> <part> x y w h dpr       (editor parts, popover-window-local)
  STRIP capture <wid> 0|1                   STRIP bind <wid> <action> <key>

Keysets come from a real KeymapManager on a throwaway config directory
(--config-dir to keep one), so hiding, showing and adding sets work and
nothing touches the user's own settings.

Reads commands on stdin: `stop`, `start` (the broadcast service),
`features <keep_alive 0|1> <click_sync 0|1>`, `style neon|flat`,
`hover <wid> 0|1` (pointer on the name), `menu <wid> <kind> <n>` (a
right-click on that block), `edit <wid> <n>` (the keyset editor), `home <wid>` (the home panel), `close`,
`quit`.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, QTimer, Signal            # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from services.toon_session_fake import FakeToonSession        # noqa: E402
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


class DemoLauncher(QObject):
    """Six accounts like the handoff's mock; a launch takes 1.3 s."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        from utils.strips.launcher_port import LaunchAccount as A
        self._make = A
        self._list = [A("a1", "ttr", "Main", "running", "Flossbud"),
                      A("a2", "ttr", "Alt 1", "running", "Hector"),
                      A("a3", "ttr", "Alt 2", "running", "Linux"),
                      A("a4", "ttr", "Alt 3"),
                      A("c1", "cc", "Clash main", "running", "Moe"),
                      A("c2", "cc", "Clash alt")]

    def accounts(self):
        return list(self._list)

    def _set(self, account_id: str, state: str) -> None:
        self._list = [self._make(a.account_id, a.game, a.label, state, a.toon)
                      if a.account_id == account_id else a for a in self._list]
        self.changed.emit()

    def launch(self, account_id: str) -> None:
        say("STRIP launch", account_id)
        self._set(account_id, "launching")
        QTimer.singleShot(1300, lambda: self._set(account_id, "running"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wid", action="append", required=True,
                    help="window id (decimal or 0x hex); repeat for up to four strips")
    ap.add_argument("--style", default="neon", choices=("neon", "flat"))
    ap.add_argument("--config-dir", default=None)
    args = ap.parse_args()
    wids = [str(int(raw, 0)) for raw in args.wid][:4]
    # Before anything reads a config file: never the user's real one.
    os.environ["TTMT_CONFIG_DIR"] = args.config_dir or tempfile.mkdtemp(
        prefix="ttmt-strip-demo-")
    from utils.keymap_manager import KeymapManager

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let Python run its signal handlers while Qt's loop is idle.
    pulse = QTimer()
    pulse.timeout.connect(lambda: None)
    pulse.start(200)

    keymaps = KeymapManager()
    for game in ("ttr", "cc"):
        while len(keymaps.get_set_ids(game)) < 3:
            keymaps.add_set(game)
    spare = [f"unused-{i}" for i in range(4 - len(wids))]
    session = FakeToonSession.demo(
        window_ids=wids + spare,
        keyset_ids={g: keymaps.get_set_ids(g) for g in ("ttr", "cc")})
    for wid in spare:
        session.remove_toon(wid)
    launcher = DemoLauncher()
    controller = StripController(session, keymap_manager=keymaps, style=args.style,
                                 launcher=launcher)
    controller.quit_requested.connect(lambda: say("STRIP wants-quit"))
    follower = controller.follower
    popovers = controller.popovers

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
    controller.appearance_requested.connect(
        lambda game, name: say("STRIP wants-appearance", game, name))
    controller.open_window_requested.connect(
        lambda target: say("STRIP wants-window", target))

    def on_counters(wid: str, shown: bool) -> None:
        surface = popovers.counters_surface(wid)
        say("STRIP counters", wid,
            int(surface.winId()) if shown and surface is not None else "hidden")

    def on_opened(wid: str, tag: str) -> None:
        surface = popovers.open_surface(wid)
        if surface is None:
            return
        content = surface.content
        dpr = surface.devicePixelRatioF()
        for i, item in enumerate(getattr(content, "items", lambda: ())()):
            r = content.pill_rect(i)
            say("STRIP pill", wid, i, f"{r.x():.1f}", f"{r.y():.1f}",
                f"{r.width():.1f}", f"{r.height():.1f}", f"{dpr:g}", item.key)
        if hasattr(content, "row_chosen"):
            def zones(content=content, wid=wid):
                for zone, _rect in content._zones:
                    r = content.zone_rect(*zone)
                    say("STRIP zone", wid, "/".join(zone), f"{r.x():.1f}", f"{r.y():.1f}",
                        f"{r.width():.1f}", f"{r.height():.1f}", f"{dpr:g}")
                card = content.card_rect()
                say("STRIP card", wid, content.view(), f"{card.x():.1f}",
                    f"{card.y():.1f}", f"{card.width():.1f}", f"{card.height():.1f}")
            zones()
            content.view_changed.connect(lambda _v: zones())
        if hasattr(content, "bind_requested"):
            for zone, _rect in content._zones:
                r = content.zone_rect(*zone)
                say("STRIP zone", wid, "/".join(zone), f"{r.x():.1f}", f"{r.y():.1f}",
                    f"{r.width():.1f}", f"{r.height():.1f}", f"{dpr:g}")
            content.bind_requested.connect(
                lambda action, key, wid=wid: say("STRIP bind", wid, action, key))
            content.capture_changed.connect(
                lambda on, wid=wid: say("STRIP capture", wid, int(on)))
        say("STRIP popover", wid, tag, int(surface.winId()))

    popovers.counters_changed.connect(on_counters)
    popovers.opened.connect(on_opened)
    popovers.closed.connect(lambda wid, tag: say("STRIP popover-closed", wid, tag))
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
        elif words[0] == "hover" and len(words) == 3:
            popovers.set_identity_hover(words[1], words[2] == "1")
        elif words[0] == "menu" and len(words) == 4:
            controller._on_context(words[1], words[2], int(words[3]))
        elif words[0] == "home" and len(words) == 2:
            controller.toggle_home_panel(words[1])
        elif words[0] == "edit" and len(words) == 3:
            controller.open_editor(words[1], int(words[2]))
        elif words[0] == "close":
            popovers.close_all()
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
