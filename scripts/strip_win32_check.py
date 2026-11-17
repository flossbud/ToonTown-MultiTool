"""Check a float strip against a stand-in game window on Windows.

The Windows twin of scripts/strip_x11_check.py: two plain windows (a "game"
and an unrelated "other"), a strip on the game through scripts/strip_demo.py,
then the windows are driven and what the strip does is asserted.

    python scripts\\strip_win32_check.py [--out FILE] [--shots DIR] [--style flat]

It must run in the logged-on user's desktop session (a process started over
ssh has no desktop): scripts\\strip_win32_rig.ps1 does that through a
scheduled task and prints the result. It injects real pointer and key input
with SendInput, so keep hands off the machine while it runs (about a minute).

What is different from X11, and why the assertions differ:
- There is no "stack directly above that window" on Windows. The strip is a
  topmost tool window and an occlusion gate masks whatever a window above
  the game covers. So "under an unrelated window" is asserted as: the strip's
  window region excludes the covered part, or the strip is not shown at all.
- The keyset editor's key capture makes its card the foreground window for
  as long as it waits for a key (WS_EX_NOACTIVATE windows get no keys
  otherwise). That one window is excluded from "never foreground"; instead
  the check asserts the game is the foreground window again afterwards.
- Escape is polled, not grabbed: it closes the menu and ALSO reaches the
  game. Reported as INFO, not as a failure.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from utils import settings_keys

ANCHOR_INSET = 10.0  # utils.strips.strip_surface.ANCHOR_INSET, logical px

WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
SW_MINIMIZE, SW_RESTORE = 6, 9
VK_ESCAPE, VK_MENU = 0x1B, 0x12
KEYEVENTF_KEYUP = 0x2
MOUSE_DOWN = {1: 0x0002, 3: 0x0008}
MOUSE_UP = {1: 0x0004, 3: 0x0010}


def child_python() -> str:
    """The interpreter for child processes whose output is read through a
    pipe. Under pythonw (no console) prefer the python.exe beside it: its
    standard streams are always real."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console):
            return console
    return exe


# Windows: a console program started from a windowless parent must not pop a
# console window of its own.
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class Proc:
    """A child process whose stdout lines are collected as they arrive."""

    def __init__(self, argv) -> None:
        self.lines: list[str] = []
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1,
                                  creationflags=NO_WINDOW)
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
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = fn()
        if got:
            return got
        time.sleep(step)
    return fn()


class WinSide:
    """Everything this check asks of or does to Windows. Physical pixels
    throughout: the process is made per-monitor DPI aware first."""

    def __init__(self) -> None:
        import win32con
        import win32gui
        self.gui, self.con = win32gui, win32con
        self.user32 = ctypes.windll.user32

    def client(self, hwnd):
        try:
            left, top, right, bottom = self.gui.GetClientRect(hwnd)
            x, y = self.gui.ClientToScreen(hwnd, (0, 0))
            return (x, y, right - left, bottom - top)
        except Exception:
            return None

    def rect(self, hwnd):
        """(x, y, w, h) of the window rectangle."""
        try:
            left, top, right, bottom = self.gui.GetWindowRect(hwnd)
            return (left, top, right - left, bottom - top)
        except Exception:
            return None

    def frame(self, hwnd):
        """(x, y, w, h) of what the window visibly covers (no resize border)."""
        from ctypes import wintypes
        rect = wintypes.RECT()
        ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if ok != 0:
            return self.rect(hwnd)
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def ex_style(self, hwnd) -> int:
        try:
            return self.gui.GetWindowLong(hwnd, self.con.GWL_EXSTYLE)
        except Exception:
            return 0

    def alive(self, hwnd) -> bool:
        return bool(self.gui.IsWindow(hwnd))

    def iconic(self, hwnd) -> bool:
        return bool(self.gui.IsIconic(hwnd))

    def foreground(self) -> int:
        return int(self.gui.GetForegroundWindow() or 0)

    def dpi(self, hwnd) -> int:
        try:
            return int(self.user32.GetDpiForWindow(hwnd))
        except Exception:
            return 96

    def region_box(self, hwnd):
        """None when the window has no region (whole window shows), else the
        region's bounding box (x, y, w, h), window-local; (0, 0, 0, 0) for an
        empty region."""
        import win32gui
        rgn = win32gui.CreateRectRgnIndirect((0, 0, 0, 0))
        try:
            try:
                kind = win32gui.GetWindowRgn(hwnd, rgn)
            except win32gui.error:         # ERROR: no region set (pywin32 raises)
                return None
            if kind == 0:
                return None
            if kind == 1:                  # NULLREGION
                return (0, 0, 0, 0)
            _kind, (left, top, right, bottom) = win32gui.GetRgnBox(rgn)
            return (left, top, right - left, bottom - top)
        finally:
            win32gui.DeleteObject(rgn)

    def move(self, hwnd, x, y, w=None, h=None) -> None:
        flags = SWP_NOZORDER | SWP_NOACTIVATE | (SWP_NOSIZE if w is None else 0)
        self.user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w or 0), int(h or 0), flags)

    def activate(self, hwnd) -> None:
        """Bring a window of another process to the front. Windows only lets
        the process that got the last input do this; a tapped Alt key makes
        us that process."""
        self.user32.keybd_event(VK_MENU, 0, 0, 0)
        self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        if self.iconic(hwnd):
            self.user32.ShowWindow(hwnd, SW_RESTORE)
        self.user32.SetForegroundWindow(hwnd)
        self.user32.BringWindowToTop(hwnd)

    def minimize(self, hwnd) -> None:
        self.user32.ShowWindow(hwnd, SW_MINIMIZE)

    def click(self, x, y, button=1) -> None:
        self.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.2)                    # let the cursor arbiter see it
        self.user32.mouse_event(MOUSE_DOWN[button], 0, 0, 0, 0)
        time.sleep(0.05)
        self.user32.mouse_event(MOUSE_UP[button], 0, 0, 0, 0)

    def key(self, vk) -> None:
        self.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        self.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


class Check:
    def __init__(self, out_path: str | None, shots: str | None) -> None:
        self.failed: list[str] = []
        self.passed = 0
        self.shots = shots
        self._n = 0
        self._app = None
        self._out = open(out_path, "w", encoding="utf-8") if out_path else None
        if shots:
            os.makedirs(shots, exist_ok=True)

    def say(self, text: str) -> None:
        try:
            print(text, flush=True)
        except Exception:
            pass
        if self._out is not None:
            self._out.write(text + "\n")
            self._out.flush()

    def ok(self, name: str, cond, detail="") -> bool:
        self.say(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
        if cond:
            self.passed += 1
        else:
            self.failed.append(name)
        return bool(cond)

    def info(self, text: str) -> None:
        self.say(f"INFO  {text}")

    def shot(self, name: str) -> None:
        """A screenshot of the whole desktop, through Qt."""
        if not self.shots:
            return
        try:
            from PySide6.QtGui import QGuiApplication
            if self._app is None:
                self._app = QGuiApplication.instance() or QGuiApplication([])
            self._n += 1
            pix = QGuiApplication.primaryScreen().grabWindow(0)
            pix.save(os.path.join(self.shots, f"{self._n:02d}-{name}.png"))
        except Exception as exc:
            self.info(f"screenshot {name} failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", default=child_python())
    ap.add_argument("--style", default="neon")
    ap.add_argument("--out", default=None, help="also write every line to this file")
    ap.add_argument("--shots", default=None)
    ap.add_argument("--origin", default="200,150",
                    help="where to put the stand-in game window (logical px)")
    args = ap.parse_args()
    if sys.platform != "win32":
        print("this check only runs on Windows; see scripts/strip_x11_check.py")
        return 2
    # Per-monitor DPI aware (v2) BEFORE any window call, or every rectangle
    # read here would be in virtualized units and disagree with the strip.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    chk = Check(args.out, args.shots)
    procs: list[Proc] = []
    try:
        code = run(args, chk, procs)
    except Exception as exc:                # a broken check must still report
        import traceback
        chk.say("FAIL  the check itself raised: " + repr(exc))
        chk.say(traceback.format_exc())
        chk.failed.append("check raised")
        code = 1
    finally:
        for p in procs:
            p.stop()
    chk.say(f"DONE passed={chk.passed} failed={len(chk.failed)}")
    return code


def run(args, chk: Check, procs) -> int:
    w = WinSide()
    gx, gy = (int(v) for v in args.origin.split(","))
    standin = Proc([args.python, os.path.join(HERE, "strip_standin.py"),
                    f"game:{gx},{gy},800,600", f"other:{gx + 900},{gy},420,360"])
    procs.append(standin)
    ids = wait_for(lambda: len(standin.find("STANDIN ")) >= 2 and standin.find("STANDIN "), 20)
    if not ids:
        chk.ok("stand-in windows came up", False, "\n".join(standin.lines))
        return 2
    wins = {ln.split()[1]: int(ln.split()[2]) for ln in ids}
    game, other = wins["game"], wins["other"]
    w.activate(game)
    time.sleep(0.6)
    wid = str(game)

    demo = Proc([args.python, os.path.join(HERE, "strip_demo.py"),
                 "--wid", wid, "--style", args.style])
    procs.append(demo)
    stamp = wait_for(lambda: demo.find("[Strips] "), 20)
    chk.ok("stamp printed", bool(stamp), stamp[0] if stamp else "no stamp")
    if not stamp:
        chk.say("\n".join(demo.lines))
        return 2
    chk.say("STAMP: " + stamp[0])
    chk.ok("attach is the Windows topmost-and-gate strategy",
           "attach=win32-topmost-gate" in stamp[0])
    size = re.search(r"size=(\w+)", stamp[0])
    configured_scale = settings_keys.float_strip_size_factor(size.group(1)) if size else 1.0
    surf = wait_for(lambda: demo.find("STRIP surface"), 5)
    strip = int(surf[0].split()[3])

    def shown_state(start=0):
        got = demo.find(f"STRIP shown {wid} ", start)
        return got[-1].endswith(" 1") if got else None

    def blocks():
        """The last full block report. A block that repeats starts a new
        report (the two separators share a name, so they do not count)."""
        last = {}
        for ln in demo.find(f"STRIP block {wid} "):
            parts = ln.split()
            key = (parts[3], int(parts[4]))
            if key[0] != "sep" and key in last:
                last = {}
            last[key] = [float(v) for v in parts[5:10]]
        return last

    def blocks_after(mark):
        """Block keys of the last full report after `mark`."""
        keys = []
        for ln in demo.find(f"STRIP block {wid} ", mark):
            parts = ln.split()
            key = (parts[3], int(parts[4]))
            if key[0] != "sep" and key in keys:
                keys = []
            keys.append(key)
        return keys

    def effective_scale() -> float:
        """The scale the strip last reported: a window too narrow for the
        configured size steps the strip down a size."""
        for ln in reversed(demo.find(f"STRIP model ")):
            try:
                data = json.loads(ln.split(" ", 2)[2])
            except (IndexError, ValueError):
                continue
            if data.get("wid") == wid:
                return float(data.get("scale", configured_scale))
        return configured_scale

    def placed_ok(label: str) -> None:
        b, s, c = blocks(), w.rect(strip), w.client(game)
        if not b or s is None or c is None:
            chk.ok(f"{label}: windows can be measured", False, f"strip {s} client {c}")
            return
        dpr = next(iter(b.values()))[4]
        left = min(v[0] for v in b.values())
        right = max(v[0] + v[2] for v in b.values())
        row_centre = s[0] + (left + right) / 2.0 * dpr
        row_top = s[1] + b[("portrait", 0)][1] * dpr
        chk.ok(f"{label}: row centred on the client area",
               abs(row_centre - (c[0] + c[2] / 2.0)) <= 2.0, f"client {c} strip {s} dpr {dpr}")
        size_scale = effective_scale()
        inset = ANCHOR_INSET * size_scale * dpr
        chk.ok(f"{label}: row top 10 px (scaled) inside the client area",
               abs(row_top - (c[1] + inset)) <= 2.0,
               f"row top {row_top:.1f} client top {c[1]} inset {inset:g} "
               f"(size scale {size_scale:g}, dpr {dpr})")

    # 1. placement and window styles
    chk.ok("strip placed and shown",
           bool(wait_for(lambda: demo.find("STRIP place") and shown_state(), 10)))
    time.sleep(0.3)
    b = blocks()
    dpr = next(iter(b.values()))[4] if b else 1.0
    dpi = w.dpi(game)
    chk.info(f"game window DPI {dpi} ({dpi / 96 * 100:.0f}%), strip pixel ratio {dpr}")
    chk.ok("the strip's pixel ratio is the window's DPI scale",
           abs(dpr - dpi / 96.0) <= 0.01, f"dpr {dpr} dpi {dpi}")
    placed_ok("at rest")
    ex = w.ex_style(strip)
    chk.ok("strip never activates (WS_EX_NOACTIVATE)", bool(ex & WS_EX_NOACTIVATE), hex(ex))
    chk.ok("strip is out of the taskbar and Alt-Tab (WS_EX_TOOLWINDOW, not APPWINDOW)",
           bool(ex & WS_EX_TOOLWINDOW) and not ex & WS_EX_APPWINDOW, hex(ex))
    chk.ok("strip is topmost", bool(ex & WS_EX_TOPMOST), hex(ex))
    chk.ok("strip is a layered (translucent) window", bool(ex & WS_EX_LAYERED), hex(ex))
    chk.ok("the game window is the foreground window", w.foreground() == game,
           hex(w.foreground()))
    chk.ok("nothing is masked off while the game is on top", w.region_box(strip) is None,
           str(w.region_box(strip)))
    chk.shot("at-rest")

    # 2. occlusion gate: a window over the game covers the strip
    s = w.rect(strip)
    mark = len(demo.lines)
    w.move(other, s[0] - 60, s[1] - 80, s[2] + 120, s[3] + 200)   # over the whole strip
    time.sleep(0.3)
    w.activate(other)
    chk.ok("a window covering the strip's place hides the strip",
           bool(wait_for(lambda: shown_state(mark) is False, 4)), str(demo.find("STRIP shown", mark)))
    chk.shot("covered")
    mark = len(demo.lines)
    half = s[0] + s[2] // 2
    w.move(other, s[0] - 200, s[1] - 80, 200 + s[2] // 2, s[3] + 200)   # left half only
    time.sleep(0.2)
    w.activate(other)
    box = wait_for(lambda: shown_state(mark) and w.region_box(strip), 4)
    edge = (w.frame(other)[0] + w.frame(other)[2]) - s[0]     # other's visible right edge
    chk.ok("a window covering half the strip masks exactly that half",
           bool(box) and abs(box[0] - edge) <= 3 and box[0] + box[2] >= s[2] - 3,
           f"region box {box}, other's visible edge at {edge} of {s[2]} (half {half - s[0]})")
    chk.shot("half-covered")
    mark = len(demo.lines)
    w.activate(game)
    wait_for(lambda: w.foreground() == game, 3)
    chk.ok("raising the game shows the whole strip again",
           bool(wait_for(lambda: w.region_box(strip) is None and shown_state() is not False, 4)),
           str(w.region_box(strip)))
    w.move(other, gx + 900, gy, 420, 360)
    time.sleep(0.6)

    # 3. pointer: blocks take clicks, the rest falls through, no activation
    b, s = blocks(), w.rect(strip)
    bx, by, bw, bh, dpr = b[("keyset", 2)]
    mark, smark = len(demo.lines), len(standin.lines)
    w.click(s[0] + (bx + bw / 2) * dpr, s[1] + (by + bh / 2) * dpr)
    chk.ok("a click on a block reaches the strip",
           bool(wait_for(lambda: [ln for ln in demo.find("STRIP click", mark)
                                  if ln.endswith("keyset 2")], 3)))
    chk.ok("that click did not reach the game window",
           not standin.find("STANDIN-CLICK game", smark))
    chk.ok("clicking a block did not take the foreground from the game",
           w.foreground() == game, hex(w.foreground()))
    px, py, pw, ph, _ = b[("sep", 0)]
    mark, smark = len(demo.lines), len(standin.lines)
    w.click(s[0] + (px + pw / 2) * dpr, s[1] + (py + ph / 2) * dpr)
    chk.ok("a click between blocks falls through to the game window",
           bool(wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)))
    chk.ok("and the strip did not take it", not demo.find("STRIP click", mark))
    smark = len(standin.lines)
    w.click(s[0] + 3, s[1] + s[3] - 3)
    chk.ok("a click on the strip window's empty margin falls through",
           bool(wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)))
    chk.ok("the game is still the foreground window", w.foreground() == game,
           hex(w.foreground()))

    # 4. hidden while moving, back in place afterwards
    gr = w.rect(game)
    mark = len(demo.lines)
    for i in range(1, 13):
        w.move(game, gr[0] + i * 15, gr[1] + i * 8)
        time.sleep(0.05)
    states = [ln.endswith(" 1") for ln in demo.find(f"STRIP shown {wid} ", mark)]
    chk.ok("the strip went out of sight when the window moved",
           bool(states) and states[0] is False, str(states))
    chk.ok("and never showed again during the drag", states.count(True) == 0, str(states))
    chk.ok("the strip is shown again once the window rests",
           bool(wait_for(lambda: demo.find("STRIP place", mark) and shown_state(mark), 4)))
    time.sleep(0.3)
    placed_ok("after the move")
    chk.shot("after-move")

    # 5. narrow window
    mark = len(demo.lines)
    w.move(game, gr[0], gr[1], int(360 * dpr) + (gr[2] - w.client(game)[2]), gr[3])
    wait_for(lambda: demo.find("STRIP place", mark) and shown_state(mark), 4)
    time.sleep(0.3)
    chk.ok("narrow window: the name plate collapsed",
           ("name", 0) not in blocks_after(mark) and bool(blocks_after(mark)),
           str(blocks_after(mark)))
    placed_ok("narrow window")
    mark = len(demo.lines)
    w.move(game, gr[0], gr[1], gr[2], gr[3])
    wait_for(lambda: demo.find("STRIP place", mark) and shown_state(mark), 4)
    time.sleep(0.3)
    back = wait_for(lambda: ("name", 0) in blocks_after(mark), 4)
    chk.ok("wide again: the name plate is back", bool(back),
           "" if back else "\n".join(demo.lines[mark:]))

    # 6. minimize and restore
    mark = len(demo.lines)
    w.minimize(game)
    chk.ok("minimizing the game hides the strip",
           bool(wait_for(lambda: shown_state(mark) is False, 4)))
    mark = len(demo.lines)
    w.activate(game)
    chk.ok("restoring the game brings the strip back",
           bool(wait_for(lambda: shown_state(mark), 6)))
    time.sleep(0.4)
    placed_ok("after restore")
    chk.ok("the game is the foreground window after restore", w.foreground() == game,
           hex(w.foreground()))

    popovers(args, chk, w, demo, standin, game, strip, wid, blocks)

    # 9. the game closes
    mark = len(demo.lines)
    standin.stop()
    chk.ok("closing the game window removes its strip",
           bool(wait_for(lambda: demo.find("STRIP gone", mark)
                         or shown_state(mark) is False, 5)))
    chk.say("")
    if chk.failed:
        chk.say(f"{len(chk.failed)} FAILED: " + "; ".join(chk.failed))
        chk.say("--- demo output ---\n" + "\n".join(demo.lines[-40:]))
        return 1
    chk.say("ALL PASSED")
    return 0


def popovers(args, chk, w, demo, standin, game, strip, wid, blocks) -> None:
    chk.say("-- popovers --")

    def styles(label, hwnd) -> None:
        ex = w.ex_style(hwnd)
        chk.ok(f"{label}: never activates, out of the taskbar, topmost",
               bool(ex & WS_EX_NOACTIVATE) and bool(ex & WS_EX_TOOLWINDOW)
               and bool(ex & WS_EX_TOPMOST), hex(ex))

    def opened(command, tag):
        mark = len(demo.lines)
        demo.send(command)
        got = wait_for(lambda: demo.find(f"STRIP popover {wid} {tag} ", mark), 4)
        return (int(got[-1].split()[4]) if got else None), mark

    # 7. a menu: its own window, no activation, Escape and click-elsewhere
    menu, mark = opened(f"menu {wid} keyset 2", "set:2")
    if chk.ok("keyset menu opens", menu is not None):
        time.sleep(0.3)
        styles("menu", menu)
        chk.ok("opening a menu left the game in the foreground", w.foreground() == game,
               hex(w.foreground()))
        chk.shot("menu-open")
        mark, smark = len(demo.lines), len(standin.lines)
        w.key(VK_ESCAPE)
        chk.ok("Escape closes the menu",
               bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
        time.sleep(0.2)
        chk.info("Escape also reached the game window: "
                 + ("yes (expected on Windows, the key is polled, not grabbed)"
                    if standin.find("STANDIN-KEY game", smark) else "no"))
    b, s = blocks(), w.rect(strip)
    kx, ky, kw, kh, dpr = b[("keyset", 2)]
    mark = len(demo.lines)
    w.click(s[0] + (kx + kw / 2) * dpr, s[1] + (ky + kh / 2) * dpr, button=3)
    chk.ok("right-click on a keyset opens its menu",
           bool(wait_for(lambda: demo.find(f"STRIP popover {wid} set:2 ", mark), 3)))
    c = w.client(game)
    mark, smark = len(demo.lines), len(standin.lines)
    w.click(c[0] + c[2] / 2, c[1] + c[3] - 80 * dpr)
    chk.ok("a click elsewhere closes the menu",
           bool(wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)))
    chk.ok("and that click still reached the game window",
           bool(wait_for(lambda: standin.find("STANDIN-CLICK game", smark), 3)))

    # 8. the keyset editor: the one window allowed to hold the keyboard
    card, mark = opened(f"edit {wid} 3", "edit:3")
    if chk.ok("keyset editor opens", card is not None):
        time.sleep(0.3)
        styles("editor", card)
        chk.ok("opening the editor left the game in the foreground", w.foreground() == game,
               hex(w.foreground()))
        chk.shot("editor-open")
        zones = {ln.split()[3]: [float(v) for v in ln.split()[4:9]]
                 for ln in demo.find(f"STRIP zone {wid} ", mark)}
        cr = w.rect(card)
        zx, zy, zw, zh, zdpr = zones["cap/gags"]
        mark, smark = len(demo.lines), len(standin.lines)
        w.click(cr[0] + (zx + zw / 2) * zdpr, cr[1] + (zy + zh / 2) * zdpr)
        chk.ok("clicking a keycap starts the capture",
               bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 1", mark), 3)))
        time.sleep(0.2)
        chk.info("foreground window during the capture: "
                 + ("the editor card (expected: it must be, to get keys)"
                    if w.foreground() == card else hex(w.foreground())))
        w.key(0x4B)                                              # K
        chk.ok("the pressed key is bound",
               bool(wait_for(lambda: demo.find(f"STRIP bind {wid} gags k", mark), 3)),
               str(demo.find("STRIP bind", mark)))
        chk.ok("the capture ended with the key",
               bool(wait_for(lambda: demo.find(f"STRIP capture {wid} 0", mark), 3)))
        chk.ok("the game is the foreground window again after the capture",
               bool(wait_for(lambda: w.foreground() == game, 3)), hex(w.foreground()))
        chk.ok("the captured key did not reach the game",
               not standin.find("STANDIN-KEY game", smark), str(standin.lines[smark:]))
        smark = len(standin.lines)
        w.key(0x4A)                                              # J
        chk.ok("and the next key goes to the game without clicking it",
               bool(wait_for(lambda: standin.find("STANDIN-KEY game", smark), 3)))
        mark = len(demo.lines)
        demo.send("close")
        wait_for(lambda: demo.find("STRIP popover-closed", mark), 3)

    panel, _ = opened(f"home {wid}", "home")
    if chk.ok("home panel opens", panel is not None):
        time.sleep(0.3)
        styles("home panel", panel)
        chk.ok("opening the home panel left the game in the foreground",
               w.foreground() == game, hex(w.foreground()))
        chk.shot("home-menu")
        demo.send("close")
        time.sleep(0.3)


if __name__ == "__main__":
    sys.exit(main())
