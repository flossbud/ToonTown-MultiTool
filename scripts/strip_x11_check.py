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
        self.p = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.p.stdout:
            self.lines.append(line.rstrip("\n"))

    def send(self, text: str) -> None:
        try:
            self.p.stdin.write(text + "\n")
            self.p.stdin.flush()
        except Exception:
            pass

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

    def composited(self) -> bool:
        """A compositing manager owns _NET_WM_CM_S<screen>."""
        atom = self.atom(f"_NET_WM_CM_S{self.d.get_default_screen()}")
        return self.d.get_selection_owner(atom) != self.X.NONE

    def bounding_rects(self, wid):
        try:
            r = self.win(wid).shape_get_rectangles(self.shape.SK.Bounding)
            return [(q.x, q.y, q.width, q.height) for q in r.rectangles]
        except Exception:
            return None

    def pixel(self, x, y):
        """(r, g, b) of one screen pixel, or None."""
        try:
            img = self.root.get_image(int(x), int(y), 1, 1, self.X.ZPixmap, 0xFFFFFFFF)
            b, g, r = img.data[0], img.data[1], img.data[2]
            return (r, g, b)
        except Exception:
            return None

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

    def key(self, keysym):
        code = self.d.keysym_to_keycode(keysym)
        self.xtest.fake_input(self.d, self.X.KeyPress, code)
        self.d.sync()
        time.sleep(0.05)
        self.xtest.fake_input(self.d, self.X.KeyRelease, code)
        self.d.sync()

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
        self.known: list[str] = []
        self.shots = shots
        self._n = 0
        if shots:
            os.makedirs(shots, exist_ok=True)

    def ok(self, name: str, cond, detail="", known: str = "") -> bool:
        """`known` names a limit of THIS window manager: a failure is then
        printed as KNOWN and not counted, so the same check stays strict on
        the window managers that matter."""
        word = "PASS" if cond else ("KNOWN" if known else "FAIL")
        note = detail if not (known and not cond) else f"{known}; {detail}"
        print(f"{word}  {name}" + (f"  [{note}]" if note else ""), flush=True)
        if not cond:
            (self.known if known else self.failed).append(name)
        return bool(cond)

    def shot(self, name: str) -> None:
        if not self.shots:
            return
        self._n += 1
        path = os.path.join(self.shots, f"{self._n:02d}-{name}.png")
        try:
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("spectacle"):
                # An X client cannot see a Wayland compositor's output.
                env = dict(os.environ, QT_QPA_PLATFORM="wayland")
                subprocess.run(["spectacle", "-b", "-n", "-f", "-o", path], env=env,
                               timeout=20, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            elif shutil.which("import"):
                subprocess.run(["import", "-window", "root", path], timeout=15,
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
        if args.xvfb:
            os.environ.pop("WAYLAND_DISPLAY", None)
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

    # No compositing manager: the strip must be a shaped window, not a
    # translucent one (which would show as a black rectangle).
    bare = not x.composited()
    if bare:
        chk.ok("stamp says there is no compositor", "compositor=none" in stamp[0], stamp[0])
        s, g = x.rect(strip), x.rect(game)
        rects = x.bounding_rects(strip) or []
        area = sum(w * h for _x, _y, w, h in rects)
        chk.ok("without a compositor the strip window is cut to its blocks",
               0 < area < 0.7 * s[2] * s[3], f"{len(rects)} rects, {area} of {s[2] * s[3]} px")
        backdrop = x.pixel(g[0] + 40, g[1] + g[3] - 40)        # the game's own colour
        inside = [(s[0] + 3, s[1] + s[3] - 3),                 # halo margin, bottom left
                  (s[0] + s[2] - 3, s[1] + s[3] - 3),          # bottom right
                  (s[0] + s[2] // 2, s[1] + s[3] - 4)]         # under the row
        seen = [x.pixel(px, py) for px, py in inside]
        chk.ok("and shows the game behind it, not black, around the blocks",
               backdrop is not None and backdrop != (0, 0, 0)
               and all(p == backdrop for p in seen), f"backdrop {backdrop} seen {seen}")

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
            hidden = x.opacity(strip) < 0.01
            if bare:        # opacity does nothing here: the shape must be empty
                hidden = hidden and x.bounding_rects(strip) == []
            seen_hidden.append(hidden)
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
    if bare:
        chk.ok("and so is the window's shape", bool(x.bounding_rects(strip)))
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

    popover_phase(args, x, chk, demo, standin, game, other, strip, gx, gy)

    # 7. the window closes: the strip stops showing
    standin.stop()
    gone = wait_for(lambda: not x.viewable(strip) or x.opacity(strip) < 0.01, 4)
    chk.ok("closing the game window hides the strip", bool(gone))
    demo.stop()

    four_windows(args, env, procs, x, chk, gx, gy)

    print()
    if chk.known:
        print(f"{len(chk.known)} KNOWN limits of this window manager: "
              + "; ".join(chk.known))
    if chk.failed:
        print(f"{len(chk.failed)} FAILED: " + "; ".join(chk.failed))
        print("--- demo output ---\n" + "\n".join(demo.lines[-40:]))
        return 1
    print("ALL PASSED")
    return 0


def popover_phase(args, x, chk, demo, standin, game, other, strip, gx, gy) -> None:
    """Counters and menus: their own windows, stacked with the strip, closed
    by Escape or a click elsewhere, and never holding the keyboard."""
    from Xlib import XK
    print("-- popovers --", flush=True)
    wid = str(game)
    quirk = ("openbox raises instead of restacking next to a sibling"
             if wm_name(x) == "Openbox" else "")

    def shown(w):
        return x.viewable(w) and x.opacity(w) > 0.99

    def blocks_now():
        last = {}
        for ln in demo.find(f"STRIP block {wid} "):
            parts = ln.split()
            last[(parts[3], int(parts[4]))] = [float(v) for v in parts[5:10]]
        return last

    def stacked_over_strip(label, w):
        order = wait_for(lambda: (lambda o: w in o and o.index(w) > o.index(strip)
                                  > o.index(game) and o)(x.stacking()), 3)
        chk.ok(f"{label}: stacked over the strip and the game", bool(order),
               str([hex(v) for v in x.stacking()]))
        chk.ok(f"{label}: tied to the strip's window",
               x.prop(w, "WM_TRANSIENT_FOR") == [strip], str(x.prop(w, "WM_TRANSIENT_FOR")))
        state = x.prop(w, "_NET_WM_STATE") or []
        chk.ok(f"{label}: out of the taskbar, not keep-above",
               x.atom("_NET_WM_STATE_SKIP_TASKBAR") in state
               and x.atom("_NET_WM_STATE_ABOVE") not in state)

    def open_menu(kind, n, tag):
        mark = len(demo.lines)
        demo.send(f"menu {wid} {kind} {n}")
        got = wait_for(lambda: demo.find(f"STRIP popover {wid} {tag} ", mark), 4)
        return (int(got[-1].split()[4]) if got else None), mark

    # Counters: the demo's first toon has them locked on.
    got = wait_for(lambda: [ln for ln in demo.find(f"STRIP counters {wid} ")
                            if not ln.endswith("hidden")], 5)
    if not chk.ok("locked counters are up", bool(got)):
        return
    counters = int(got[-1].split()[3])
    chk.ok("counters are shown", bool(wait_for(lambda: shown(counters), 4)),
           f"viewable {x.viewable(counters)} opacity {x.opacity(counters):.2f}")
    stacked_over_strip("counters", counters)
    b = blocks_now()
    s, c = x.rect(strip), x.rect(counters)
    left = b[("portrait", 0)][0]
    right = b[("name", 0)][0] + b[("name", 0)][2]
    chk.ok("counters are centred under portrait and name",
           abs((c[0] + c[2] / 2.0) - (s[0] + (left + right) / 2.0)) <= 1.5,
           f"counters {c} strip {s} identity {left}..{right}")
    row_bottom = s[1] + b[("portrait", 0)][1] + b[("portrait", 0)][3]
    chk.ok("counters start at the row's bottom edge (no gap to cross)",
           abs(c[1] - row_bottom) <= 1, f"counters y {c[1]} row bottom {row_bottom}")

    # A menu, opened without the pointer.
    menu, _ = open_menu("keyset", 2, "set:2")
    if not chk.ok("keyset menu opens", menu is not None):
        return
    chk.ok("menu is shown", bool(wait_for(lambda: shown(menu), 4)))
    stacked_over_strip("menu", menu)
    chk.ok("menu did not take focus", x.active() == game, hex(x.active()))
    x.move_resize(other, gx + 150, gy - 60, 520, 300)
    time.sleep(0.4)
    x.activate(other)
    over = wait_for(lambda: (lambda o: o.index(other) > max(o.index(menu), o.index(counters),
                                                             o.index(strip)) and o)(x.stacking()), 3)
    chk.ok("a window raised over the game covers the menu and counters too", bool(over),
           str([hex(v) for v in x.stacking()]))
    chk.shot("popovers-covered")
    x.activate(game)
    wait_for(lambda: x.active() == game, 3)
    x.move_resize(other, gx + 900, gy, 420, 360)
    time.sleep(0.5)
    stacked_over_strip("menu after raising the game", menu)
    chk.shot("menu-open")

    if args.no_pointer:
        print("SKIP  Escape, click-elsewhere and menu clicks (--no-pointer)")
        mark = len(demo.lines)
        demo.send("close")
        chk.ok("menu closes on request",
               bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
    else:
        # Escape closes the menu and does not reach the game.
        mark, smark = len(demo.lines), len(standin.lines)
        x.key(XK.XK_Escape)
        chk.ok("Escape closes the menu",
               bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
        time.sleep(0.2)
        chk.ok("that Escape did not reach the game window",
               not standin.find("STANDIN-KEY game", smark), str(standin.lines[smark:]))
        chk.ok("focus stayed on the game window", x.active() == game, hex(x.active()))
        smark = len(standin.lines)
        x.key(XK.XK_a)
        chk.ok("with the menu closed the game gets the keyboard again",
               bool(wait_for(lambda: standin.find("STANDIN-KEY game", smark), 3)))
        smark = len(standin.lines)
        x.key(XK.XK_Escape)
        chk.ok("and Escape is the game's again",
               bool(wait_for(lambda: standin.find("STANDIN-KEY game", smark), 3)))

        # A real right-click opens it; a click elsewhere closes it and still
        # reaches the game.
        b = blocks_now()
        s = x.rect(strip)
        kx, ky, kw, kh, dpr = b[("keyset", 2)]
        mark = len(demo.lines)
        x.click(s[0] + (kx + kw / 2) * dpr, s[1] + (ky + kh / 2) * dpr, button=3)
        got = wait_for(lambda: demo.find(f"STRIP popover {wid} set:2 ", mark), 3)
        chk.ok("right-click on a keyset opens its menu", bool(got))
        g = x.rect(game)
        mark, smark = len(demo.lines), len(standin.lines)
        x.click(g[0] + g[2] / 2, g[1] + g[3] - 80)
        chk.ok("a click elsewhere closes the menu",
               bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
        chk.ok("and that click still reached the game window",
               bool(wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)))

        # Hide keyset 2 from the menu.
        mark = len(demo.lines)
        x.click(s[0] + (kx + kw / 2) * dpr, s[1] + (ky + kh / 2) * dpr, button=3)
        got = wait_for(lambda: demo.find(f"STRIP popover {wid} set:2 ", mark), 3)
        pills = {ln.split()[-1]: [float(v) for v in ln.split()[4:9]]
                 for ln in demo.find(f"STRIP pill {wid} ", mark)}
        if chk.ok("menu reopens with its items", bool(got) and "hide" in pills, str(pills)):
            m = x.rect(int(got[-1].split()[4]))
            px, py, pw, ph, pdpr = pills["hide"]
            before = x.rect(strip)[2]
            x.click(m[0] + (px + pw / 2) * pdpr, m[1] + (py + ph / 2) * pdpr)
            # One 28 px block and its 6 px gap fewer.
            shrunk = wait_for(lambda: x.rect(strip)[2] == before - 34 * dpr, 3)
            chk.ok("Hide keyset removes that button from the strip", bool(shrunk),
                   f"strip width {x.rect(strip)[2]} was {before}")
            chk.ok("clicking a menu item left focus on the game", x.active() == game,
                   hex(x.active()))

    editor_steps(args, x, chk, demo, standin, game, strip, wid, shown, stacked_over_strip)
    home_steps(args, x, chk, demo, standin, game, strip, wid, shown, stacked_over_strip,
               blocks_now)

    # Moving the window takes everything with it; locked counters come back.
    menu, mark = open_menu("keyset", 1, "set:1")
    chk.ok("menu open before the move", menu is not None)
    for i in range(1, 9):
        x.move_resize(game, gx + i * 15, gy + i * 6)
        time.sleep(0.05)
    chk.ok("moving the window closes the menu",
           bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
    chk.ok("and hides the counters while it moves",
           x.opacity(counters) < 0.01 or not x.viewable(counters))
    back = wait_for(lambda: shown(counters) and shown(strip), 4)
    time.sleep(0.3)
    s, c = x.rect(strip), x.rect(counters)
    b = blocks_now()
    left = b[("portrait", 0)][0]
    right = b[("name", 0)][0] + b[("name", 0)][2]
    chk.ok("locked counters return under the strip at the new place",
           bool(back) and abs((c[0] + c[2] / 2.0) - (s[0] + (left + right) / 2.0)) <= 1.5,
           f"counters {c} strip {s}")
    chk.shot("popovers-after-move")
    x.move_resize(game, gx, gy)
    time.sleep(0.6)


def editor_steps(args, x, chk, demo, standin, game, strip, wid, shown,
                 stacked_over_strip) -> None:
    """The keyset editor: the one popover that may hold the keyboard, and
    only while it waits for a key."""
    from Xlib import XK
    mark = len(demo.lines)
    demo.send(f"edit {wid} 3")
    got = wait_for(lambda: demo.find(f"STRIP popover {wid} edit:3 ", mark), 4)
    if not chk.ok("keyset editor opens", bool(got)):
        return
    card = int(got[-1].split()[4])
    chk.ok("editor is shown", bool(wait_for(lambda: shown(card), 4)))
    stacked_over_strip("editor", card)
    chk.ok("opening the editor left focus on the game", x.active() == game, hex(x.active()))
    chk.shot("editor-open")
    if args.no_pointer:
        print("SKIP  press-a-key capture and keyboard hand-back (--no-pointer)")
        demo.send("close")
        time.sleep(0.3)
        return
    zones = {ln.split()[3]: [float(v) for v in ln.split()[4:9]]
             for ln in demo.find(f"STRIP zone {wid} ", mark)}
    c = x.rect(card)

    def click_zone(name):
        zx, zy, zw, zh, dpr = zones[name]
        x.click(c[0] + (zx + zw / 2) * dpr, c[1] + (zy + zh / 2) * dpr)

    def game_keys(since):
        return standin.find("STANDIN-KEY game", since)

    def game_gets_a_key(label):
        since = len(standin.lines)
        x.key(XK.XK_j)
        chk.ok(label, bool(wait_for(lambda: game_keys(since), 3)), hex(x.active()))

    # 1. Click a keycap, press a key: bound, and the keyboard goes straight back.
    mark, smark = len(demo.lines), len(standin.lines)
    click_zone("cap/gags")
    chk.ok("clicking a keycap starts the capture",
           bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 1", mark), 3)))
    chk.ok("the game window is still the active window during the capture",
           x.active() == game, hex(x.active()))
    x.key(XK.XK_k)
    chk.ok("the pressed key is bound",
           bool(wait_for(lambda: demo.find(f"STRIP bind {wid} gags k", mark), 3)),
           str(demo.find("STRIP bind", mark)))
    chk.ok("the capture ended with the key",
           bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 0", mark), 3)))
    time.sleep(0.2)
    chk.ok("the captured key did not reach the game", not game_keys(smark),
           str(standin.lines[smark:]))
    game_gets_a_key("after the capture the keyboard is the game's again")

    # 2. Escape cancels: nothing bound, card still open, keyboard back.
    mark, smark = len(demo.lines), len(standin.lines)
    c = x.rect(card)
    click_zone("cap/tasks")
    wait_for(lambda: demo.find(f"STRIP capture {wid} 1", mark), 3)
    x.key(XK.XK_Escape)
    chk.ok("Escape cancels the capture",
           bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 0", mark), 3)))
    time.sleep(0.2)
    chk.ok("nothing was bound and the card stayed open",
           not demo.find("STRIP bind", mark) and not demo.find("STRIP popover-closed", mark)
           and shown(card))
    chk.ok("that Escape did not reach the game", not game_keys(smark))
    game_gets_a_key("after a cancelled capture the keyboard is the game's again")

    # 3. Clicking elsewhere mid-capture closes the card and frees the keyboard.
    mark = len(demo.lines)
    click_zone("cap/tasks")
    wait_for(lambda: demo.find(f"STRIP capture {wid} 1", mark), 3)
    g = x.rect(game)
    x.click(g[0] + g[2] / 2, g[1] + g[3] - 60)
    chk.ok("a click elsewhere mid-capture closes the editor",
           bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
    chk.ok("and ends the capture",
           bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 0", mark), 3)))
    game_gets_a_key("after the editor closed mid-capture the keyboard is the game's again")
    chk.ok("focus never left the game window", x.active() == game, hex(x.active()))


def home_steps(args, x, chk, demo, standin, game, strip, wid, shown,
               stacked_over_strip, blocks_now) -> None:
    """The home block's panel: quick menu, then the compact launcher."""
    mark = len(demo.lines)
    demo.send(f"home {wid}")
    got = wait_for(lambda: demo.find(f"STRIP popover {wid} home ", mark), 4)
    if not chk.ok("home panel opens", bool(got)):
        return
    panel = int(got[-1].split()[4])
    chk.ok("home panel is shown", bool(wait_for(lambda: shown(panel), 4)))
    stacked_over_strip("home panel", panel)
    chk.ok("home panel did not take focus", x.active() == game, hex(x.active()))

    def card(since):
        line = demo.find(f"STRIP card {wid} ", since)[-1].split()
        return line[3], [float(v) for v in line[4:8]]

    view, (cx, cy, cw, ch) = card(mark)
    s, p = x.rect(strip), x.rect(panel)
    hx, hy, hw, hh, dpr = blocks_now()[("home", 0)]
    chk.ok("quick menu's card is left-aligned with the home block, 10 px below it",
           view == "menu" and abs((p[0] + cx * dpr) - (s[0] + hx * dpr)) <= 1.5
           and abs((p[1] + cy * dpr) - (s[1] + (hy + hh) * dpr) - 10 * dpr) <= 1.5,
           f"panel {p} card {(cx, cy)} strip {s} home {(hx, hy, hw, hh)}")
    chk.shot("home-menu")
    if args.no_pointer:
        print("SKIP  home panel clicks (--no-pointer)")
        demo.send("close")
        time.sleep(0.3)
        return
    zones = {ln.split()[3]: [float(v) for v in ln.split()[4:9]]
             for ln in demo.find(f"STRIP zone {wid} ", mark)}

    def click_zone(name, zs):
        zx, zy, zw, zh, zdpr = zs[name]
        pr = x.rect(panel)
        x.click(pr[0] + (zx + zw / 2) * zdpr, pr[1] + (zy + zh / 2) * zdpr)

    mark2 = len(demo.lines)
    click_zone("row/launch", zones)
    swapped = wait_for(lambda: [ln for ln in demo.find(f"STRIP card {wid} ", mark2)
                                if ln.split()[3] == "launch"], 3)
    chk.ok("Launch accounts swaps the menu for the compact launcher", bool(swapped))
    time.sleep(0.3)
    chk.ok("the panel stayed open and on show", shown(panel)
           and not demo.find("STRIP popover-closed", mark2))
    zones2 = {ln.split()[3]: [float(v) for v in ln.split()[4:9]]
              for ln in demo.find(f"STRIP zone {wid} ", mark2)}
    chk.shot("home-launcher")
    if chk.ok("an idle account has a Launch button", "go/a4" in zones2, str(sorted(zones2))):
        mark3 = len(demo.lines)
        click_zone("go/a4", zones2)
        chk.ok("Launch starts that account",
               bool(wait_for(lambda: demo.find("STRIP launch a4", mark3), 3)))
    mark4, smark = len(demo.lines), len(standin.lines)
    g = x.rect(game)
    x.click(g[0] + g[2] / 2, g[1] + g[3] - 60)
    chk.ok("a click elsewhere closes the home panel",
           bool(wait_for(lambda: demo.find("STRIP popover-closed", mark4), 3)))
    chk.ok("focus stayed on the game throughout", x.active() == game, hex(x.active()))


def four_windows(args, env, procs, x, chk, gx, gy) -> None:
    """One strip per toon from the session: four stand-ins, each its own
    process so one can close on its own."""
    print("-- four windows, one session --", flush=True)
    spots = [(gx, gy, 620, 330), (gx + 660, gy, 620, 330),
             (gx, gy + 380, 620, 330), (gx + 660, gy + 380, 300, 330)]
    games = []
    for i, (px, py, pw, ph) in enumerate(spots):
        proc = Proc([args.python, os.path.join(HERE, "strip_standin.py"),
                     f"game{i + 1}:{px},{py},{pw},{ph}"], env)
        procs.append(proc)
        games.append(proc)
    ids = []
    for proc in games:
        got = wait_for(lambda p=proc: p.find("STANDIN "), 15)
        if not got:
            chk.ok("four stand-in windows came up", False)
            return
        ids.append(int(got[0].split()[2]))
    time.sleep(0.5)

    argv = [args.python, os.path.join(HERE, "strip_demo.py"), "--style", args.style]
    for wid in ids:
        argv += ["--wid", str(wid)]
    demo = Proc(argv, env)
    procs.append(demo)
    surf = wait_for(lambda: len(demo.find("STRIP surface")) == 4 and demo.find("STRIP surface"), 15)
    if not surf:
        chk.ok("four strips were created", False, "\n".join(demo.lines[-10:]))
        return
    strips = {int(ln.split()[2]): int(ln.split()[3]) for ln in surf}

    def shown(strip):
        return x.viewable(strip) and x.opacity(strip) > 0.99

    up = wait_for(lambda: all(shown(s) for s in strips.values()), 8)
    chk.ok("four strips shown, one per window", bool(up),
           str({hex(g): (x.viewable(s), round(x.opacity(s), 2)) for g, s in strips.items()}))
    time.sleep(0.3)
    for i, wid in enumerate(ids):
        g, s = x.rect(wid), x.rect(strips[wid])
        chk.ok(f"toon {i + 1}: strip centred on its own window",
               abs((g[0] + g[2] / 2.0) - (s[0] + s[2] / 2.0)) <= 1.0
               and abs((s[1] + MARGIN) - (g[1] + INSET)) <= 1, f"game {g} strip {s}")
        chk.ok(f"toon {i + 1}: strip tied to its own window",
               x.prop(strips[wid], "WM_TRANSIENT_FOR") == [wid])
    # Openbox answers a restack-next-to-a-sibling request with a plain raise,
    # so strips mapped after several windows sit in a block above all of
    # them until each window is next raised. KWin and mutter restack in place.
    quirk = ("openbox raises instead of restacking next to a sibling"
             if wm_name(x) == "Openbox" else "")
    order = x.stacking()
    chk.ok("each strip is above its own window",
           all(order.index(strips[w]) > order.index(w) for w in ids),
           str([hex(w) for w in order]))
    chk.ok("each strip is directly above its own window",
           all(order.index(strips[w]) == order.index(w) + 1 for w in ids),
           str([hex(w) for w in order]), known=quirk)

    def blocks_of(wid, start=0):
        last = {}
        for ln in demo.find(f"STRIP block {wid} ", start):
            parts = ln.split()
            last[(parts[3], int(parts[4]))] = parts
        return last

    chk.ok("home block is on toon 1's strip only",
           demo.find("STRIP home")[-1].endswith(str(ids[0]))
           and ("home", 0) in blocks_of(ids[0])
           and not any(("home", 0) in blocks_of(w) for w in ids[1:]))
    chk.ok("Corporate Clash strip has no Click Sync block",
           ("click_sync", 0) not in blocks_of(ids[2])
           and ("click_sync", 0) in blocks_of(ids[1]))
    chk.ok("the narrow fourth window collapsed its name plate",
           ("name", 0) not in blocks_of(ids[3]) and ("name", 0) in blocks_of(ids[0]))
    chk.shot("four-strips")

    # Raising one game window must not lift the other strips.
    x.activate(ids[1])
    time.sleep(0.5)
    order = x.stacking()
    chk.ok("raising a window carries its own strip to the top with it",
           order.index(strips[ids[1]]) == order.index(ids[1]) + 1
           and order.index(strips[ids[1]]) == max(order.index(v) for v in
                                                  list(strips.values()) + ids),
           str([hex(w) for w in order]))
    chk.ok("and the other strips stay directly above their own windows",
           all(order.index(strips[w]) == order.index(w) + 1 for w in ids),
           str([hex(w) for w in order]), known=quirk)

    # Toon 1's window closes: its strip goes, the home block moves on.
    width_before = x.rect(strips[ids[1]])[2]
    mark = len(demo.lines)
    games[0].stop()
    moved = wait_for(lambda: demo.find("STRIP home", mark), 6)
    chk.ok("toon 1 closed: home block moved to the next strip",
           bool(moved) and moved[-1].endswith(str(ids[1])), str(moved))
    gone = wait_for(lambda: not x.viewable(strips[ids[0]]), 4)
    chk.ok("toon 1 closed: its strip is gone", bool(gone))
    grown = wait_for(lambda: (x.rect(strips[ids[1]]) or (0, 0, 0))[2] == width_before + 37, 4)
    g, s = x.rect(ids[1]), x.rect(strips[ids[1]])
    chk.ok("the next strip grew by the home block and stayed centred",
           bool(grown) and abs((g[0] + g[2] / 2.0) - (s[0] + s[2] / 2.0)) <= 1.0,
           f"width {s[2]} was {width_before}, game {g} strip {s}")
    chk.ok("the other strips are still shown",
           all(shown(strips[w]) for w in ids[1:]))
    chk.shot("home-moved")

    # App-wide switches reach every strip.
    mark = len(demo.lines)
    demo.send("features 0 1")
    wait_for(lambda: demo.find("STRIP did features", mark), 3)
    narrower = wait_for(lambda: x.rect(strips[ids[1]])[2] == width_before + 37 - 34, 4)
    chk.ok("Keep-Alive off app-wide: the block is gone from the strip", bool(narrower),
           f"width {x.rect(strips[ids[1]])[2]}")
    demo.send("features 1 1")
    demo.send("stop")
    wait_for(lambda: demo.find("STRIP did stop", mark), 3)
    time.sleep(0.3)
    chk.ok("strips stay up when the service is stopped",
           all(shown(strips[w]) for w in ids[1:]))
    chk.shot("stopped")
    demo.stop()
    for proc in games[1:]:
        proc.stop()


def wm_name(x: XSide) -> str:
    try:
        check = x.root_prop("_NET_SUPPORTING_WM_CHECK")
        p = x.win(check[0]).get_full_property(x.atom("_NET_WM_NAME"), x.X.AnyPropertyType)
        return p.value.decode() if isinstance(p.value, bytes) else str(p.value)
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
