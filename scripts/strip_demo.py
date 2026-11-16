"""Float strips on stand-in windows, without the rest of the app.

  PLAYGROUND, for a person to click on:

    python scripts/strip_demo.py --play [--style neon|flat]

  Opens four plain windows standing in for game windows (the third stands for
  a Corporate Clash toon, the fourth is narrow) and puts a live strip on each:
  the real strip controller on the fake session's four demo toons, a real
  keymap manager on a throwaway settings folder (your own settings are never
  read or written), and a pretend launcher with accounts in every state.
  Every action it receives is printed as one `ACTION ...` line, and every
  click or key that reaches a stand-in window as `GAME ...`. It ends when you
  choose Quit MultiTool, close all four windows, or it is stopped; it leaves
  nothing running and removes its settings folder.

  ON AN EXISTING WINDOW, for checks:

    python scripts/strip_demo.py --wid 0x2400007 [--wid ...] [--style flat]

  Each --wid is a window id as the platform names it (X11 XID, HWND), up to
  four. Prints the machine-readable `STRIP ...` lines scripts/strip_x11_check.py
  reads (also printed in the playground with --trace).

Things to try in the playground, and what should happen:

  1. Click each block. Keep-Alive, Click Sync and Enable toggle; a keyset
     number becomes the lit one; + adds a keyset. The window underneath keeps
     keyboard focus the whole time (type: GAME key lines keep coming).
  2. Click between two blocks, and on the window's title bar right above the
     strip: the click reaches the window (GAME click) or drags it; the strip
     never takes it.
  3. Hover a name: counters appear under it. Move down onto the lock without
     them closing; click the lock; they stay. Click it again; they go when the
     pointer leaves.
  4. Right-click a keyset: Edit keyset, Hide keyset. Hide one: a dot appears
     on the +, and the + lists it for restoring.
  5. Right-click a portrait or name: Lock counters, Change color..., Stop all
     toons (every strip dims, each Enable keeps its own state), Open MultiTool.
  6. With a menu open press Esc: it closes and NO `GAME key` line for Esc
     appears. Click anywhere else: it closes and the click still lands
     (GAME click).
  7. Edit keyset, click a keycap, press a key: it is bound (ACTION bind), and
     the very next key you type shows as `GAME key` again without clicking
     the window first. Try Esc during the capture (cancels, nothing bound) and
     the Keys layout (pick an action, click a key).
  8. Click the app icon on the first strip: the quick menu. Launch accounts
     swaps to the compact launcher; Launch on an idle account goes
     Launching... then running. Close the first window: the icon moves to the
     next strip.
  9. Drag a window by its title bar: its strip vanishes while it moves and
     comes back in place when it rests. It must never trail behind.
 10. Put another window over a stand-in: it covers the strip and anything
     hanging off it. Minimize a stand-in: its strip goes with it and returns.
 11. Alt-Tab and the taskbar: no strip, counters or menu is ever listed.
 12. Make the fourth window wider and narrower: the name plate collapses and
     returns.

Commands on stdin (checks use these): `stop`, `start`, `features <ka 0|1>
<cs 0|1>`, `style neon|flat`, `hover <wid> 0|1`, `menu <wid> <kind> <n>`,
`edit <wid> <n>`, `home <wid>`, `close`, `quit`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QObject, QTimer, Signal            # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from services.toon_session_fake import FakeToonSession        # noqa: E402
from utils.strips.controller import StripController           # noqa: E402
from utils.strips.follow import _platform_geometry            # noqa: E402

GONE_AFTER = 3      # consecutive missing samples before a window counts as closed

# name : x, y, w, h : title. A title must never CONTAIN a game's full name:
# on Windows the app adopts any window whose title contains "Toontown
# Rewritten" or "Corporate Clash" as a game window.
PLAY_WINDOWS = (
    "game1:120,120,760,420:Stand-in 1 (TTR toon, has the home block)",
    "game2:920,120,760,420:Stand-in 2 (TTR toon)",
    "game3:120,640,760,420:Stand-in 3 (Clash toon, no Click Sync)",
    "game4:920,640,330,420:Stand-in 4 (narrow)",
)

TRACE = True


def say(*parts) -> None:
    """Machine-readable line for the check scripts."""
    if TRACE:
        print(*parts, flush=True)


def act(*parts) -> None:
    """One plain line per action the strips ask for."""
    print("ACTION", *parts, flush=True)


class Lines(QObject):
    """Lines from another thread (stdin, a child's stdout), on the GUI thread."""

    line = Signal(str, str)      # source, text

    def follow(self, source: str, stream) -> None:
        def read() -> None:
            try:
                for raw in stream:
                    self.line.emit(source, raw.rstrip("\n"))
                self.line.emit(source, "\x00eof")
            except Exception:
                pass          # the stream closed, or the app is already gone
        threading.Thread(target=read, daemon=True).start()


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
        label = next((a.label for a in self._list if a.account_id == account_id), "?")
        act(f"launch asked for account {account_id} ({label})")
        say("STRIP launch", account_id)
        self._set(account_id, "launching")
        QTimer.singleShot(1300, lambda: self._set(account_id, "running"))


def log_keymaps(keymaps) -> None:
    """Print every write the strips make to the keymap manager."""
    def wrap(name, describe):
        real = getattr(keymaps, name)

        def logged(*args, **kwargs):
            act(describe(*args, **kwargs))
            return real(*args, **kwargs)
        setattr(keymaps, name, logged)

    wrap("update_set_key", lambda game, index, action, key:
         f"bind: {game} keyset {index + 1}, {action} = {key}")
    wrap("add_set", lambda game, *a, **k: f"new keyset asked for {game}")
    wrap("set_hidden", lambda game, set_id, hidden:
         f"keyset {keymaps.index_of(game, set_id) + 1} of {game} "
         f"{'hidden' if hidden else 'shown again'}")


def log_session(session, keysets) -> None:
    """Print what changed on a toon, by comparing its state before and after."""
    last = {t.window_id: t for t in session.toons()}

    def changed(wid: str) -> None:
        new, old = session.toon(wid), last.get(wid)
        if new is None:
            return
        last[wid] = new
        if old is None:
            return
        who = new.name or wid
        for field, text in (("enabled", "enabled"), ("keep_alive", "keep-alive"),
                            ("click_sync", "click sync"),
                            ("counters_locked", "counters locked")):
            if getattr(new, field) != getattr(old, field):
                act(f"{who}: {text} {'ON' if getattr(new, field) else 'OFF'}")
        if new.keyset_id != old.keyset_id:
            act(f"{who}: keyset {keysets.number_for(new.game, new.keyset_id)} selected")

    session.toon_changed.connect(changed)
    session.running_changed.connect(
        lambda on: act("all toons " + ("STARTED" if on else "STOPPED")))


def main() -> int:
    global TRACE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--play", action="store_true",
                    help="open four stand-in windows and put strips on them")
    ap.add_argument("--wid", action="append", default=[],
                    help="window id (decimal or 0x hex); repeat for up to four strips")
    ap.add_argument("--style", default="neon", choices=("neon", "flat"))
    ap.add_argument("--config-dir", default=None,
                    help="settings folder to use and keep (default: a temporary one)")
    ap.add_argument("--trace", action="store_true",
                    help="in the playground, also print the STRIP ... lines")
    args = ap.parse_args()
    if not args.play and not args.wid:
        ap.error("give --play, or one or more --wid")
    TRACE = bool(args.wid) or args.trace

    # Before anything reads a config file: never the user's real one.
    own_config = None
    if args.config_dir:
        os.environ["TTMT_CONFIG_DIR"] = args.config_dir
    else:
        own_config = tempfile.mkdtemp(prefix="ttmt-strip-demo-")
        os.environ["TTMT_CONFIG_DIR"] = own_config
    from utils.keymap_manager import KeymapManager

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let Python run its signal handlers while Qt's loop is idle.
    pulse = QTimer()
    pulse.timeout.connect(lambda: None)
    pulse.start(200)

    lines = Lines()
    children: list[subprocess.Popen] = []
    state: dict = {"controller": None, "ids": {}}

    def start(wids: list[str]) -> None:
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
        controller = StripController(session, keymap_manager=keymaps,
                                     style=args.style, launcher=launcher)
        state.update(controller=controller, session=session, launcher=launcher)
        follower, popovers = controller.follower, controller.popovers
        log_keymaps(keymaps)
        log_session(session, controller.keysets)

        def asked_to_quit() -> None:
            act("quit asked")
            say("STRIP wants-quit")
            if args.play:
                QTimer.singleShot(300, app.quit)

        controller.quit_requested.connect(asked_to_quit)
        controller.appearance_requested.connect(
            lambda game, name: (act(f"looks editor asked for {name} ({game})"),
                                say("STRIP wants-appearance", game, name)))
        controller.open_window_requested.connect(
            lambda target: (act(f"open window asked: {target}"),
                            say("STRIP wants-window", target)))
        controller.home_moved.connect(
            lambda wid: (act(f"home block is on {session.toon(wid).name}'s strip"),
                         say("STRIP home", wid)))

        def report_blocks(wid: str) -> None:
            """Block rectangles local to the strip window, plus the pixel
            ratio, so an outside check can aim a pointer at them."""
            surface = follower.surface(wid)
            if surface is None or not TRACE:
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

            def zones() -> None:
                for zone, _rect in content._zones:
                    r = content.zone_rect(*zone)
                    say("STRIP zone", wid, "/".join(zone), f"{r.x():.1f}", f"{r.y():.1f}",
                        f"{r.width():.1f}", f"{r.height():.1f}", f"{dpr:g}")

            if hasattr(content, "row_chosen"):
                def panel() -> None:
                    zones()
                    card = content.card_rect()
                    say("STRIP card", wid, content.view(), f"{card.x():.1f}",
                        f"{card.y():.1f}", f"{card.width():.1f}", f"{card.height():.1f}")
                panel()
                content.view_changed.connect(lambda _v: panel())
            if hasattr(content, "bind_requested"):
                zones()
                content.bind_requested.connect(
                    lambda action, key: say("STRIP bind", wid, action, key))
                content.capture_changed.connect(
                    lambda on: (act("waiting for a key (the strip has the keyboard)" if on
                                    else "key capture ended (keyboard released)"),
                                say("STRIP capture", wid, int(on))))
            say("STRIP popover", wid, tag, int(surface.winId()))

        names = {"toon": "toon menu", "add": "+ menu", "home": "home panel"}

        def what(tag: str) -> str:
            kind, _, n = tag.partition(":")
            if kind == "set":
                return f"keyset {n} menu"
            if kind == "edit":
                return f"keyset {n} editor"
            return names.get(tag, tag)

        def who(wid: str) -> str:
            toon = session.toon(wid)
            return (toon.name if toon is not None and toon.name else wid)

        popovers.counters_changed.connect(on_counters)
        popovers.opened.connect(on_opened)
        popovers.opened.connect(
            lambda wid, tag: act(f"{who(wid)}: {what(tag)} opened"))
        popovers.closed.connect(
            lambda wid, tag: (act(f"{who(wid)}: {what(tag)} closed"),
                              say("STRIP popover-closed", wid, tag)))
        controller.start()
        for wid, surface in follower.surfaces().items():
            surface.strip.clicked.connect(
                lambda kind, n, wid=wid: say("STRIP click", wid, kind, n))
            say("STRIP surface", wid, int(surface.winId()))

        # Stand in for the window manager service: a window that stays gone is
        # a game that closed.
        missing: dict[str, int] = {}

        def watch() -> None:
            for toon in session.toons():
                wid = toon.window_id
                if _platform_geometry(wid) is None:
                    missing[wid] = missing.get(wid, 0) + 1
                    if missing[wid] >= GONE_AFTER:
                        act(f"{toon.name}'s window closed: strip removed")
                        say("STRIP gone", wid)
                        session.remove_toon(wid)
                else:
                    missing.pop(wid, None)
            if args.play and not session.toons():
                act("every stand-in window is closed: ending")
                app.quit()

        watcher = QTimer(app)
        watcher.timeout.connect(watch)
        watcher.start(250)

    def command(text: str) -> None:
        controller = state["controller"]
        words = text.split()
        if not words or controller is None:
            return
        session, popovers = state["session"], controller.popovers
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

    def on_line(source: str, text: str) -> None:
        if source == "stdin":
            if text != "\x00eof":
                command(text.strip())
            return
        # A stand-in window's own report.
        if text == "\x00eof":
            return
        words = text.split()
        if words[:1] == ["STANDIN"] and len(words) == 3:
            state["ids"][source] = str(int(words[2]))
            if len(state["ids"]) == len(children) and state["controller"] is None:
                order = [f"game{i + 1}" for i in range(len(children))]
                start([state["ids"][name] for name in order])
        elif words[:1] == ["STANDIN-CLICK"]:
            print("GAME", source, "got a click at", *words[2:], flush=True)
        elif words[:1] == ["STANDIN-KEY"]:
            print("GAME", source, "got key", *words[3:], flush=True)

    lines.line.connect(on_line)
    lines.follow("stdin", sys.stdin)

    if args.play:
        print("Float strip playground. Quit from the app icon's menu (Quit MultiTool), "
              "or close the four windows.", flush=True)
        for spec in PLAY_WINDOWS:
            child = subprocess.Popen(
                [sys.executable, os.path.join(HERE, "strip_standin.py"), spec],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            children.append(child)
            lines.follow(spec.split(":", 1)[0], child.stdout)
    else:
        start([str(int(raw, 0)) for raw in args.wid][:4])

    code = app.exec()

    controller = state["controller"]
    if controller is not None:
        controller.shutdown()
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
    if own_config:
        shutil.rmtree(own_config, ignore_errors=True)
    if args.play:
        print("Playground ended; nothing left running.", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
