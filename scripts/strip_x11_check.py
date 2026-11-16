"""Check a float strip against a stand-in game window on X11.

Starts two plain windows (a "game" and an unrelated "other"), puts a strip on
the game with scripts/strip_demo.py, then drives the windows and asserts what
the strip does: where it sits, where it stacks, that it hides while its
window moves, that it never takes focus and that clicks outside its blocks
reach the window underneath.

    python scripts/strip_x11_check.py --xvfb          # own Xvfb + openbox
    python scripts/strip_x11_check.py                 # the current DISPLAY

Under --xvfb this is a construction check (no compositor, a different window
manager from any real desktop). Against a real desktop's DISPLAY it is a live
check of the stand-in window, not of a game.

Needs python-xlib. --shots DIR saves a screenshot per step with `import`
(ImageMagick) or `spectacle` when one is installed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARGIN = 14          # utils.strips.strip_widget.MARGIN
INSET = 10           # utils.strips.strip_surface.ANCHOR_INSET


class Proc:
    """A child process whose stdout lines are collected as they arrive."""

    def __init__(self, argv, env) -> None:
        self.lines: list[str] = []
        self.p = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.p.stdout:
            self.lines.append(line.rstrip("\n"))

    def find(self, prefix: str, start: int = 0) -> list[str]:
        return [ln for ln in self.lines[start:] if ln.startswith(prefix)]

    def stop(self) -> None:
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.p.kill()


def wait_for(fn, timeout=5.0, step=0.02):
    """Poll `fn` until it returns something truthy; returns it or None."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = fn()
        if got:
            return got
        time.sleep(step)
    return fn()


class XSide:
    """Everything this check asks of or does to the X server."""

    def __init__(self) -> None:
        from Xlib import X, Xatom, display
        from Xlib.ext import shape, xtest
        self.X, self.Xatom, self.shape, self.xtest = X, Xatom, shape, xtest
        self.d = display.Display()
        self.root = self.d.screen().root

    def atom(self, name):
        return self.d.intern_atom(name)

    def win(self, wid):
        return self.d.create_resource_object("window", int(wid))

    def prop(self, wid, name):
        try:
            p = self.win(wid).get_full_property(self.atom(name), self.X.AnyPropertyType)
            return list(p.value) if p is not None else None
        except Exception:
            return None

    def root_prop(self, name):
        p = self.root.get_full_property(self.atom(name), self.X.AnyPropertyType)
        return list(p.value) if p is not None else []

    def rect(self, wid):
        """Client rectangle in root coordinates, or None."""
        try:
            w = self.win(wid)
            c = self.root.translate_coords(w, 0, 0)
            g = w.get_geometry()
            return (c.x, c.y, g.width, g.height)
        except Exception as exc:
            self.last_error = repr(exc)
            return None

    def viewable(self, wid) -> bool:
        try:
            return self.win(wid).get_attributes().map_state == self.X.IsViewable
        except Exception:
            return False

    def stacking(self):
        return self.root_prop("_NET_CLIENT_LIST_STACKING")

    def active(self):
        got = self.root_prop("_NET_ACTIVE_WINDOW")
        return got[0] if got else 0

    def opacity(self, wid) -> float:
        got = self.prop(wid, "_NET_WM_WINDOW_OPACITY")
        return 1.0 if not got else got[0] / 0xFFFFFFFF

    def input_rects(self, wid):
        try:
            r = self.win(wid).shape_get_rectangles(self.shape.SK.Input)
            return [(q.x, q.y, q.width, q.height) for q in r.rectangles]
        except Exception:
            return None

    def _message(self, wid, name, data):
        from Xlib.protocol import event
        ev = event.ClientMessage(window=self.win(wid), client_type=self.atom(name),
                                 data=(32, (list(data) + [0] * 5)[:5]))
        self.root.send_event(ev, event_mask=self.X.SubstructureRedirectMask
                             | self.X.SubstructureNotifyMask)
        self.d.flush()

    def activate(self, wid):
        self._message(wid, "_NET_ACTIVE_WINDOW", [2, self.X.CurrentTime, 0])

    def move_resize(self, wid, x, y, w=None, h=None):
        # gravity static (10), source pager (2 << 12), flags for x, y, w, h
        flags = (10) | (1 << 8) | (1 << 9) | (2 << 12)
        if w is not None:
            flags |= (1 << 10) | (1 << 11)
        self._message(wid, "_NET_MOVERESIZE_WINDOW", [flags, x, y, w or 0, h or 0])

    def minimize(self, wid):
        self._message(wid, "WM_CHANGE_STATE", [3])       # IconicState

    def click(self, x, y, button=1):
        self.xtest.fake_input(self.d, self.X.MotionNotify, x=int(x), y=int(y))
        self.d.sync()
        time.sleep(0.15)
        self.xtest.fake_input(self.d, self.X.ButtonPress, button)
        self.d.sync()
        time.sleep(0.05)
        self.xtest.fake_input(self.d, self.X.ButtonRelease, button)
        self.d.sync()


class Check:
    def __init__(self, shots: str | None) -> None:
        self.failed: list[str] = []
        self.shots = shots
        self._n = 0
        if shots:
            os.makedirs(shots, exist_ok=True)

    def ok(self, name: str, cond, detail="") -> bool:
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""),
              flush=True)
        if not cond:
            self.failed.append(name)
        return bool(cond)

    def shot(self, name: str) -> None:
        if not self.shots:
            return
        self._n += 1
        path = os.path.join(self.shots, f"{self._n:02d}-{name}.png")
        try:
            if shutil.which("import"):
                subprocess.run(["import", "-window", "root", path], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("spectacle"):
                subprocess.run(["spectacle", "-b", "-n", "-f", "-o", path], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xvfb", action="store_true",
                    help="start a private Xvfb and openbox and run inside them")
    ap.add_argument("--display", default=None,
                    help="display for --xvfb (default: the first free one from :97)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--style", default="neon")
    ap.add_argument("--shots", default=None)
    ap.add_argument("--no-pointer", action="store_true",
                    help="skip the steps that inject pointer clicks")
    ap.add_argument("--origin", default="200,150",
                    help="where to put the stand-in game window")
    args = ap.parse_args()

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "xcb"
    env.pop("QT_SCALE_FACTOR", None)
    procs: list = []
    servers: list = []
    try:
        if args.xvfb:
            if not args.display:
                # Two checks on one display would drive each other's windows.
                n = 97
                while os.path.exists(f"/tmp/.X11-unix/X{n}") or os.path.exists(f"/tmp/.X{n}-lock"):
                    n += 1
                args.display = f":{n}"
            env["DISPLAY"] = args.display
            env.pop("XAUTHORITY", None)
            env.pop("WAYLAND_DISPLAY", None)
            servers.append(subprocess.Popen(
                ["Xvfb", args.display, "-screen", "0", "1600x900x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(1.0)
            servers.append(subprocess.Popen(["openbox"], env=env,
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL))
            time.sleep(1.0)
        os.environ["DISPLAY"] = env.get("DISPLAY", "")
        if env.get("XAUTHORITY"):
            os.environ["XAUTHORITY"] = env["XAUTHORITY"]
        return run(args, env, procs)
    finally:
        for p in procs:
            p.stop()
        for s in reversed(servers):
            s.terminate()
            try:
                s.wait(timeout=3)
            except subprocess.TimeoutExpired:
                s.kill()


def run(args, env, procs) -> int:
    x = XSide()
    chk = Check(args.shots)
    gx, gy = (int(v) for v in args.origin.split(","))
    gw, gh = 800, 600
    print(f"window manager: {wm_name(x)}   display: {env.get('DISPLAY')}", flush=True)

    standin = Proc([args.python, os.path.join(HERE, "strip_standin.py"),
                    f"game:{gx},{gy},{gw},{gh}",
                    f"other:{gx + 900},{gy},420,360"], env)
    procs.append(standin)
    ids = wait_for(lambda: len(standin.find("STANDIN ")) >= 2 and standin.find("STANDIN "), 15)
    if not ids:
        print("FAIL  stand-in windows did not come up\n" + "\n".join(standin.lines))
        return 2
    wins = {ln.split()[1]: int(ln.split()[2]) for ln in ids}
    game, other = wins["game"], wins["other"]
    x.activate(game)
    time.sleep(0.5)

    demo = Proc([args.python, os.path.join(HERE, "strip_demo.py"),
                 "--wid", str(game), "--style", args.style], env)
    procs.append(demo)
    stamp = wait_for(lambda: demo.find("[Strips] "), 15)
    chk.ok("stamp printed", bool(stamp), stamp[0] if stamp else "no stamp")
    if not stamp:
        print("\n".join(demo.lines))
        return 2
    print("STAMP:", stamp[0], flush=True)
    chk.ok("attach is the X11 transient strategy", "attach=x11-transient" in stamp[0])
    surf = wait_for(lambda: demo.find("STRIP surface"), 5)
    strip = int(surf[0].split()[3])

    def shown():
        return x.viewable(strip) and x.opacity(strip) > 0.99

    def placed_ok(label: str) -> None:
        g, s = x.rect(game), x.rect(strip)
        if g is None or s is None:
            chk.ok(f"{label}: windows can be measured", False,
                   f"game {g} strip {s} {getattr(x, 'last_error', '')}")
            return
        centre_g = g[0] + g[2] / 2.0
        centre_s = s[0] + s[2] / 2.0
        chk.ok(f"{label}: row centred on the client area",
               abs(centre_g - centre_s) <= 1.0, f"game {g} strip {s}")
        chk.ok(f"{label}: row top 10 px inside the client area",
               abs((s[1] + MARGIN) - (g[1] + INSET)) <= 1, f"strip y {s[1]} client y {g[1]}")

    def directly_above(label: str) -> None:
        st = wait_for(lambda: (lambda o: game in o and strip in o
                               and o.index(strip) == o.index(game) + 1 and o)(x.stacking()), 3)
        chk.ok(f"{label}: strip stacked directly above its window", bool(st),
               f"stacking {[hex(w) for w in x.stacking()]} game {hex(game)} strip {hex(strip)}")

    # 1. placement, tie, stacking
    chk.ok("strip placed and shown", bool(wait_for(lambda: demo.find("STRIP place") and shown(), 8)),
           f"viewable {x.viewable(strip)} opacity {x.opacity(strip):.2f}")
    placed_ok("at rest")
    chk.ok("WM_TRANSIENT_FOR points at the game window",
           x.prop(strip, "WM_TRANSIENT_FOR") == [game], str(x.prop(strip, "WM_TRANSIENT_FOR")))
    state = x.prop(strip, "_NET_WM_STATE") or []
    chk.ok("strip is kept out of the taskbar",
           x.atom("_NET_WM_STATE_SKIP_TASKBAR") in state)
    chk.ok("strip is not keep-above", x.atom("_NET_WM_STATE_ABOVE") not in state)
    wtype = x.prop(strip, "_NET_WM_WINDOW_TYPE") or []
    chk.ok("strip is not a DOCK window", x.atom("_NET_WM_WINDOW_TYPE_DOCK") not in wtype)
    directly_above("at rest")
    chk.ok("the game window still has focus", x.active() == game, hex(x.active()))
    chk.shot("at-rest")

    # 2. an unrelated window raised over the game covers the strip too
    x.move_resize(other, gx + 150, gy - 60, 520, 300)
    time.sleep(0.4)
    x.activate(other)
    order = wait_for(lambda: (lambda o: o.index(other) > o.index(strip) > o.index(game) and o)(
        x.stacking()), 3)
    chk.ok("other window raised over the game is above the strip", bool(order),
           f"{[hex(w) for w in x.stacking()]}")
    chk.shot("covered-by-other")
    x.activate(game)
    order = wait_for(lambda: (lambda o: o.index(strip) > o.index(game) > o.index(other) and o)(
        x.stacking()), 3)
    chk.ok("raising the game carries the strip above the other window", bool(order),
           f"{[hex(w) for w in x.stacking()]}")
    directly_above("after raising the game")
    x.move_resize(other, gx + 900, gy, 420, 360)
    time.sleep(0.5)
    chk.shot("game-raised")

    # 3. pointer: blocks take clicks, everything else falls through, no focus
    blocks = {}
    for ln in demo.find("STRIP block"):
        _a, _b, _wid, kind, n, bx, by, bw, bh, dpr = ln.split()
        blocks[(kind, int(n))] = tuple(float(v) for v in (bx, by, bw, bh, dpr))
    if args.no_pointer:
        print("SKIP  pointer steps (--no-pointer)")
    elif not blocks:
        chk.ok("demo reported block rectangles", False)
    else:
        s = x.rect(strip)
        bx, by, bw, bh, dpr = blocks[("keyset", 2)]
        mark = len(demo.lines)
        smark = len(standin.lines)
        x.click(s[0] + (bx + bw / 2) * dpr, s[1] + (by + bh / 2) * dpr)
        hit = wait_for(lambda: [ln for ln in demo.find("STRIP click", mark)
                                if ln.endswith("keyset 2")], 3)
        chk.ok("a click on a block reaches the strip", bool(hit))
        chk.ok("that click did not reach the game window",
               not standin.find("STANDIN-CLICK game", smark))
        chk.ok("clicking a block left focus on the game window", x.active() == game,
               hex(x.active()))
        # The separator between tools and keysets is paint only.
        px, py, pw, ph, _ = blocks[("sep", 0)]
        smark, mark = len(standin.lines), len(demo.lines)
        x.click(s[0] + (px + pw / 2) * dpr, s[1] + (py + ph / 2) * dpr)
        got = wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)
        chk.ok("a click between blocks falls through to the game window", bool(got))
        chk.ok("and the strip did not take it", not demo.find("STRIP click", mark))
        smark = len(standin.lines)
        x.click(s[0] + 3, s[1] + s[3] - 3)           # halo margin, inside the client
        got = wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)
        chk.ok("a click on the strip window's empty margin falls through", bool(got))
        chk.ok("focus never moved to the strip", x.active() == game, hex(x.active()))
        chk.shot("after-clicks")

    # 4. hide while moving, come back in place
    mark = len(demo.lines)
    seen_hidden = []
    seen_inputless = []
    for i in range(1, 13):                         # a 12-step drag, ~0.6 s
        x.move_resize(game, gx + i * 15, gy + i * 8)
        time.sleep(0.05)
        if i >= 5:                                 # well past one sample period
            seen_hidden.append(x.opacity(strip) < 0.01)
            seen_inputless.append(x.input_rects(strip) == [])
    chk.ok("strip is invisible throughout the drag", all(seen_hidden), str(seen_hidden))
    chk.ok("and takes no input while invisible", all(seen_inputless), str(seen_inputless))
    chk.ok("tracker reported the move", bool(demo.find("STRIP hide", mark)))
    back = wait_for(lambda: demo.find("STRIP place", mark) and shown(), 3)
    chk.ok("strip is shown again once the window rests", bool(back),
           f"opacity {x.opacity(strip):.2f}")
    time.sleep(0.2)
    placed_ok("after the move")
    directly_above("after the move")
    chk.ok("input region is back on the blocks", bool(x.input_rects(strip)))
    chk.shot("after-move")

    # 5. narrow window: the name plate collapses, the strip still fits
    mark = len(demo.lines)
    before = x.rect(strip)[2]
    x.move_resize(game, gx, gy, 360, gh)
    back = wait_for(lambda: demo.find("STRIP place", mark) and shown(), 3)
    time.sleep(0.2)
    s, g = x.rect(strip), x.rect(game)
    chk.ok("narrow window: strip re-placed", bool(back))
    chk.ok("narrow window: strip collapsed to fit",
           s[2] < before and s[2] - 2 * MARGIN <= g[2] - 24, f"strip {s} game {g}")
    placed_ok("narrow window")
    chk.shot("narrow")
    mark = len(demo.lines)
    x.move_resize(game, gx, gy, gw, gh)
    wait_for(lambda: demo.find("STRIP place", mark) and shown(), 3)
    time.sleep(0.2)
    chk.ok("wide again: full strip is back", x.rect(strip)[2] == before,
           f"{x.rect(strip)[2]} vs {before}")

    # 6. minimize with the window, come back with it
    x.minimize(game)
    gone = wait_for(lambda: not x.viewable(game) and not x.viewable(strip), 4)
    chk.ok("minimizing the game takes the strip with it", bool(gone),
           f"game viewable {x.viewable(game)} strip viewable {x.viewable(strip)}")
    chk.shot("minimized")
    x.activate(game)
    back = wait_for(lambda: x.viewable(game) and shown(), 5)
    chk.ok("restoring the game brings the strip back", bool(back),
           f"strip viewable {x.viewable(strip)} opacity {x.opacity(strip):.2f}")
    time.sleep(0.3)
    placed_ok("after restore")
    directly_above("after restore")
    chk.ok("focus is on the game after restore, not the strip", x.active() != strip,
           hex(x.active()))
    chk.shot("restored")

    # 7. the window closes: the strip stops showing
    standin.stop()
    gone = wait_for(lambda: not x.viewable(strip) or x.opacity(strip) < 0.01, 4)
    chk.ok("closing the game window hides the strip", bool(gone))

    print()
    if chk.failed:
        print(f"{len(chk.failed)} FAILED: " + "; ".join(chk.failed))
        print("--- demo output ---\n" + "\n".join(demo.lines[-40:]))
        return 1
    print("ALL PASSED")
    return 0


def wm_name(x: XSide) -> str:
    try:
        check = x.root_prop("_NET_SUPPORTING_WM_CHECK")
        p = x.win(check[0]).get_full_property(x.atom("_NET_WM_NAME"), x.X.AnyPropertyType)
        return p.value.decode() if isinstance(p.value, bytes) else str(p.value)
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
