#!/usr/bin/env python3
"""Click Sync Phase-0 spike. Standalone; do not import app modules.

Usage:
  python3 scripts/click_sync_spike.py list
  python3 scripts/click_sync_spike.py record [seconds]
  python3 scripts/click_sync_spike.py click  <wid> <rx> <ry> [--mask masked|zero]
  python3 scripts/click_sync_spike.py drag   <wid> <rx1> <ry1> <rx2> <ry2> [--mask masked|zero]

rx/ry are relative coords in [0,1] of the client window (0.93 0.05 is roughly
the Friends icon area at the top right).
"""
import sys
import time

from Xlib import X, display as xdisplay
from Xlib.ext import record
from Xlib.protocol import event as xevent, rq

GAME_MARKER = "Toontown Rewritten"


def _find_ttr_windows(d):
    """(wid, title, x, y, w, h) for every TTR client window."""
    out = []
    root = d.screen().root

    def walk(win):
        try:
            wm_class = win.get_wm_class()
            name = win.get_wm_name()
        except Exception:
            wm_class, name = None, None
        cls = (wm_class[1] if wm_class and len(wm_class) >= 2 else "") or ""
        if GAME_MARKER in cls or (name and str(name).startswith(GAME_MARKER)):
            try:
                coords = root.translate_coords(win, 0, 0)
                geo = win.get_geometry()
                out.append((win.id, str(name), int(coords.x), int(coords.y),
                            int(geo.width), int(geo.height)))
            except Exception:
                pass
            return
        try:
            for ch in win.query_tree().children:
                walk(ch)
        except Exception:
            pass

    walk(root)
    return out


def cmd_list():
    d = xdisplay.Display()
    for wid, name, x, y, w, h in _find_ttr_windows(d):
        print(f"wid={wid} pos=({x},{y}) size={w}x{h} aspect={w/h:.4f} name={name!r}")
    d.close()


def cmd_record(seconds):
    """Prove XRecord sees physical button + motion device events on this server."""
    ctl = xdisplay.Display()
    data = xdisplay.Display()
    if not ctl.has_extension("RECORD"):
        print("FAIL: RECORD extension not available")
        return
    ctx = ctl.record_create_context(0, [record.AllClients], [{
        "core_requests": (0, 0), "core_replies": (0, 0),
        "ext_requests": (0, 0, 0, 0), "ext_replies": (0, 0, 0, 0),
        "delivered_events": (0, 0),
        "device_events": (X.ButtonPress, X.MotionNotify),  # 4..6: press, release, motion
        "errors": (0, 0), "client_started": False, "client_died": False,
    }])
    ctl.sync()
    deadline = time.monotonic() + seconds
    count = {"press": 0, "release": 0, "motion": 0}

    def cb(reply):
        if reply.category != record.FromServer or reply.client_swapped:
            return
        buf = reply.data
        while len(buf) >= 32:
            ev, buf = rq.EventField(None).parse_binary_value(
                buf, data.display, None, None)
            kind = {X.ButtonPress: "press", X.ButtonRelease: "release",
                    X.MotionNotify: "motion"}.get(ev.type)
            if kind:
                count[kind] += 1
                if kind != "motion":
                    print(f"  {kind} btn={ev.detail} root=({ev.root_x},{ev.root_y}) "
                          f"state={ev.state} time={ev.time} send_event={ev.send_event}")
        if time.monotonic() > deadline:
            ctl.record_disable_context(ctx)
            ctl.flush()

    print(f"Recording for {seconds}s; click and move the mouse anywhere...")

    # Watchdog: the deadline above only fires inside the callback, so with
    # ZERO captured events (the exact failure this probe detects) the enable
    # call would block forever. The main thread blocks on `data`, so using
    # `ctl` from this thread is safe.
    import threading

    def _watchdog():
        time.sleep(seconds + 2)
        try:
            ctl.record_disable_context(ctx)
            ctl.flush()
        except Exception:
            pass

    threading.Thread(target=_watchdog, daemon=True).start()
    data.record_enable_context(ctx, cb)  # blocks until disabled
    ctl.record_free_context(ctx)
    ctl.close(); data.close()
    print(f"counts: {count}")
    missing = [k for k, v in count.items() if v == 0]
    if not missing:
        print("PASS")
    else:
        print(f"FAIL: no {'/'.join(missing)} events captured "
              "(if press/release are missing, XRecord is unusable -> feature infeasible)")


def _geom(d, wid):
    win = d.create_resource_object("window", wid)
    root = d.screen().root
    c = root.translate_coords(win, 0, 0)
    g = win.get_geometry()
    return win, int(c.x), int(c.y), int(g.width), int(g.height)


def _send_button(d, win, wx, wy, rx_root, ry_root, press, mask_mode, t=X.CurrentTime,
                 state_release=X.Button1MotionMask):
    cls = xevent.ButtonPress if press else xevent.ButtonRelease
    ev = cls(time=t, root=d.screen().root, window=win, same_screen=1, child=X.NONE,
             root_x=rx_root, root_y=ry_root, event_x=wx, event_y=wy,
             state=(0 if press else 256), detail=1)  # 256 = Button1Mask on release
    if mask_mode == "zero":
        win.send_event(ev, propagate=False, event_mask=0)
    else:
        win.send_event(ev, propagate=False,
                       event_mask=(X.ButtonPressMask if press else X.ButtonReleaseMask))
    d.flush()


def _send_motion(d, win, wx, wy, rx_root, ry_root, mask_mode):
    ev = xevent.MotionNotify(time=X.CurrentTime, root=d.screen().root, window=win,
                             same_screen=1, child=X.NONE, root_x=rx_root, root_y=ry_root,
                             event_x=wx, event_y=wy, state=256, detail=0)
    if mask_mode == "zero":
        win.send_event(ev, propagate=False, event_mask=0)
    else:
        # Dragging clients usually select ButtonMotionMask/Button1MotionMask,
        # not PointerMotionMask; include all three or they miss the event.
        motion_mask = (X.PointerMotionMask | X.ButtonMotionMask
                       | X.Button1MotionMask)
        win.send_event(ev, propagate=False, event_mask=motion_mask)
    d.flush()


def cmd_click(wid, rx, ry, mask_mode):
    d = xdisplay.Display()
    win, x, y, w, h = _geom(d, wid)
    wx, wy = int(rx * w), int(ry * h)
    print(f"clicking wid={wid} at client=({wx},{wy}) (size {w}x{h}) mask={mask_mode}")
    _send_button(d, win, wx, wy, x + wx, y + wy, True, mask_mode)
    time.sleep(0.06)
    _send_button(d, win, wx, wy, x + wx, y + wy, False, mask_mode)
    d.close()


def cmd_drag(wid, rx1, ry1, rx2, ry2, mask_mode):
    d = xdisplay.Display()
    win, x, y, w, h = _geom(d, wid)
    x1, y1 = int(rx1 * w), int(ry1 * h)
    x2, y2 = int(rx2 * w), int(ry2 * h)
    print(f"dragging wid={wid} ({x1},{y1}) -> ({x2},{y2}) mask={mask_mode}")
    _send_button(d, win, x1, y1, x + x1, y + y1, True, mask_mode)
    steps = 12
    for i in range(1, steps + 1):
        mx = x1 + (x2 - x1) * i // steps
        my = y1 + (y2 - y1) * i // steps
        _send_motion(d, win, mx, my, x + mx, y + my, mask_mode)
        time.sleep(0.016)
    _send_button(d, win, x2, y2, x + x2, y + y2, False, mask_mode)
    d.close()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); return 2
    mask = "masked"
    if "--mask" in args:
        mi = args.index("--mask")
        val = args[mi + 1] if mi + 1 < len(args) else None
        if val == "zero":
            mask = "zero"
        elif val != "masked":
            print(f"warning: unrecognized --mask value {val!r}; using 'masked'")
    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "record":
        cmd_record(max(0, int(args[1])) if len(args) > 1 else 10)
    elif cmd == "click":
        cmd_click(int(args[1]), float(args[2]), float(args[3]), mask)
    elif cmd == "drag":
        cmd_drag(int(args[1]), float(args[2]), float(args[3]),
                 float(args[4]), float(args[5]), mask)
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
