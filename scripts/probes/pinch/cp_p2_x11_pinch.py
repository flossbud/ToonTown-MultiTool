#!/usr/bin/env python3
"""CP-P2: do XInput 2.4 touchpad pinch gesture events reach X11 client windows?

Purpose
-------
XI 2.4 (X server / XWayland >= 21.1 with libinput) defines gesture events
GesturePinchBegin=27, GesturePinchUpdate=28, GesturePinchEnd=29 (and swipe
30/31/32).  python-xlib's xinput module negotiates only XI 2.0 in its
query_version helper and has no gesture support at all, so this probe does
the version handshake and the gesture-mask event selection at the raw
request level, reusing python-xlib's own request Structs
(Xlib.ext.xinput.XIQueryVersion / XISelectEvents) with hand-chosen values.

It answers two questions:
  1. Does the target session deliver pinch gesture events to ordinary
     client windows, and to override-redirect windows (the app's overlay
     windows are override-redirect on X11)?
  2. What do the raw event bytes look like?  Every gesture event is dumped
     as a full hex string so the dumps can be pasted into parser tests as
     fixtures later.  Field decodes are printed as GUESSES only (labelled
     *_guess); the real semantics are read off the captured data, never
     assumed from this script.

Run instructions (Linux box only; DOES NOT run on macOS)
--------------------------------------------------------
    python3 scripts/probes/pinch/cp_p2_x11_pinch.py

Requires python-xlib (pip install python-xlib).  No app imports, no Qt.

Run it once inside an Xorg session and once inside a Wayland session
(where it talks to XWayland); the delivery answer may differ.  While it
runs: hover the pointer over each colored window in turn, pinch on the
touchpad, and also two-finger scroll (control data proving plain XI event
delivery works).  Ctrl+C to quit.
"""

# Constraints:
# - Self-contained: python-xlib only.  No project imports, no Qt.
# - Linux/X11 only.  On any other display stack it exits with a message.
# - Never claims gesture-field semantics: decodes are labelled guesses and
#   the raw bytes are always printed in full.

import os
import select
import signal
import struct
import sys

try:
    import Xlib
    from Xlib import X, display as xdisplay
    from Xlib.ext import ge, xinput
except ImportError as exc:  # pragma: no cover - probe guard
    print("cp_p2_x11_pinch: python-xlib is required: %s" % exc)
    sys.exit(1)


# ----------------------------------------------------------------------
# XI 2.4 constants (inputproto XI2.h).  python-xlib 0.33 stops at
# RawMotion=17, so the gesture codes are spelled out here.
# ----------------------------------------------------------------------
XI_GESTURE_PINCH_BEGIN = 27
XI_GESTURE_PINCH_UPDATE = 28
XI_GESTURE_PINCH_END = 29
XI_GESTURE_SWIPE_BEGIN = 30
XI_GESTURE_SWIPE_UPDATE = 31
XI_GESTURE_SWIPE_END = 32

EVTYPE_NAMES = {
    xinput.DeviceChanged: "DeviceChanged",
    xinput.KeyPress: "KeyPress",
    xinput.KeyRelease: "KeyRelease",
    xinput.ButtonPress: "ButtonPress",
    xinput.ButtonRelease: "ButtonRelease",
    xinput.Motion: "Motion",
    xinput.Enter: "Enter",
    xinput.Leave: "Leave",
    xinput.FocusIn: "FocusIn",
    xinput.FocusOut: "FocusOut",
    XI_GESTURE_PINCH_BEGIN: "GesturePinchBegin",
    XI_GESTURE_PINCH_UPDATE: "GesturePinchUpdate",
    XI_GESTURE_PINCH_END: "GesturePinchEnd",
    XI_GESTURE_SWIPE_BEGIN: "GestureSwipeBegin",
    XI_GESTURE_SWIPE_UPDATE: "GestureSwipeUpdate",
    XI_GESTURE_SWIPE_END: "GestureSwipeEnd",
}

GESTURE_EVTYPES = (
    XI_GESTURE_PINCH_BEGIN,
    XI_GESTURE_PINCH_UPDATE,
    XI_GESTURE_PINCH_END,
    XI_GESTURE_SWIPE_BEGIN,
    XI_GESTURE_SWIPE_UPDATE,
    XI_GESTURE_SWIPE_END,
)

GENERIC_EVENT_CODE = ge.GenericEventCode  # 35

WIN_W = 300
WIN_H = 300

_stop = False


def _on_sigint(signum, frame):
    # Flag-based stop keeps the exit path single and clean; the select()
    # loop below notices the flag on the next tick.
    global _stop
    _stop = True


# ----------------------------------------------------------------------
# Environment metadata
# ----------------------------------------------------------------------

def print_environment(disp):
    print("=== CP-P2 environment ===")
    print("XDG_SESSION_TYPE    = %r" % os.environ.get("XDG_SESSION_TYPE"))
    print("WAYLAND_DISPLAY     = %s" % (
        "set (%r)" % os.environ["WAYLAND_DISPLAY"]
        if "WAYLAND_DISPLAY" in os.environ else "unset"))
    print("XDG_CURRENT_DESKTOP = %r" % os.environ.get("XDG_CURRENT_DESKTOP"))
    print("DISPLAY             = %r" % os.environ.get("DISPLAY"))
    ver = getattr(Xlib, "__version_string__", None) or str(
        getattr(Xlib, "__version__", "unknown"))
    print("python-xlib version = %s" % ver)
    info = getattr(disp.display, "info", None)
    vendor = getattr(info, "vendor", None)
    release = getattr(info, "release_number", None)
    if isinstance(vendor, bytes):
        vendor = vendor.decode("latin-1", "replace")
    print("X server vendor     = %r" % vendor)
    print("X server release    = %r" % release)
    print()


# ----------------------------------------------------------------------
# XI 2.4 handshake.
#
# python-xlib's xinput.query_version() helper hardcodes client version
# 2.0, which makes the server treat this client as pre-gesture and reject
# gesture mask bits.  The XIQueryVersion request Struct itself is version
# agnostic, so it is reused directly with major=2 minor=4 - the same
# construction query_version() uses, minus the hardcoded numbers.
# ----------------------------------------------------------------------

def xi_query_version_24(disp):
    reply = xinput.XIQueryVersion(
        display=disp.display,
        opcode=disp.display.get_extension_major(xinput.extname),
        major_version=2,
        minor_version=4,
    )
    return reply.major_version, reply.minor_version


# ----------------------------------------------------------------------
# Gesture event selection.
#
# xinput.select_events() would work mechanically, but the mask value is
# built here explicitly and the XISelectEvents request Struct is invoked
# directly so the wire layout is under this probe's control.  python-xlib's
# xinput.Mask packer expands an arbitrary-size Python int into as many
# native-order CARD32 words as needed (it does NOT cap the mask length),
# and the highest bit used here is 29 which fits in a single CARD32 - so
# no manual byte packing is required.  If a future mask needed bits >= 32,
# passing a plain int would still produce the correct multi-word mask.
# ----------------------------------------------------------------------

def xi_select_events(disp, window, deviceid, mask_bits):
    mask = 0
    for bit in mask_bits:
        mask |= 1 << bit
    xinput.XISelectEvents(
        display=disp.display,
        opcode=disp.display.get_extension_major(xinput.extname),
        window=window,
        masks=[(deviceid, mask)],
    )


# ----------------------------------------------------------------------
# Test windows
# ----------------------------------------------------------------------

def alloc_pixel(screen, r, g, b, fallback):
    # 16-bit-per-channel color allocation; falls back to a stock pixel if
    # the colormap refuses (unlikely on TrueColor).
    try:
        cell = screen.default_colormap.alloc_color(r, g, b)
        if cell is not None:
            return cell.pixel
    except Exception:
        pass
    return fallback


def make_window(disp, screen, x, y, pixel, title, override):
    win = screen.root.create_window(
        x, y, WIN_W, WIN_H, 2,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=pixel,
        override_redirect=1 if override else 0,
        event_mask=X.ExposureMask | X.StructureNotifyMask,
    )
    win.set_wm_name(title)
    gc = win.create_gc(foreground=pixel, background=screen.black_pixel)
    win.map()
    return win, gc


def repaint(win, gc):
    win.fill_rectangle(gc, 0, 0, WIN_W, WIN_H)


# ----------------------------------------------------------------------
# Raw dump + guess decoding
# ----------------------------------------------------------------------

def fp1616(raw_i32):
    # FP1616 fixed point: signed 16.16 (mirrors Xlib.ext.xinput.FP1616).
    return raw_i32 / 65536.0


def u16(data, off):
    return struct.unpack("=H", data[off:off + 2])[0]


def u32(data, off):
    return struct.unpack("=I", data[off:off + 4])[0]


def i32(data, off):
    return struct.unpack("=i", data[off:off + 4])[0]


def guess_event_window(data):
    """Best-effort read of the XI event-window field.

    In XI2 device, enter/leave, and (per the inputproto 2.4 structs)
    gesture events, the `event` window sits at offset 14 of the payload
    that follows the 10-byte GenericEvent header.  This is used only to
    tag which probe window an event landed on - it is a guess like every
    other decode here.
    """
    if len(data) >= 18:
        return u32(data, 14)
    return None


def dump_gesture_event(evtype, header, data, win_label):
    # Full wire packet = 10-byte GenericEvent header (type, extension,
    # sequence, length, evtype) + payload.  Both are dumped so the hex
    # string can be replayed byte-for-byte as a parser fixture.
    raw_hex = (header + data).hex()
    print("[raw win=%s] evtype=%d len=%d bytes=%s"
          % (win_label, evtype, len(header) + len(data), raw_hex))

    # Offsets below are payload-relative (payload starts right after the
    # 10-byte GenericEvent header, i.e. at the deviceid field) and follow
    # the xXIGesturePinchEvent layout from inputproto 2.4.  Everything is
    # a GUESS to be verified against the captured bytes - hence the
    # *_guess labels and the dual fp1616/int32 decode of each pinch field.
    if len(data) < 62:
        print("[guess] payload shorter than expected gesture layout"
              " (%d bytes) - raw dump above is the authority" % len(data))
        return
    print(
        "[guess] deviceid=%d time=%d detail_fingercount_guess=%d"
        " root=0x%x event=0x%x child=0x%x"
        " root_x=%.4f root_y=%.4f event_x=%.4f event_y=%.4f"
        % (
            u16(data, 0),          # deviceid
            u32(data, 2),          # time
            u32(data, 6),          # detail (finger count?)
            u32(data, 10),         # root window
            u32(data, 14),         # event window
            u32(data, 18),         # child window
            fp1616(i32(data, 22)),  # root_x FP1616
            fp1616(i32(data, 26)),  # root_y FP1616
            fp1616(i32(data, 30)),  # event_x FP1616
            fp1616(i32(data, 34)),  # event_y FP1616
        )
    )
    pinch_fields = (
        ("delta_x", 38),
        ("delta_y", 42),
        ("delta_unaccel_x", 46),
        ("delta_unaccel_y", 50),
        ("scale", 54),
        ("delta_angle", 58),
    )
    parts = []
    for name, off in pinch_fields:
        raw = i32(data, off)
        parts.append("%s_fp1616_guess=%.6f (raw_int32=%d)"
                     % (name, fp1616(raw), raw))
    if len(data) >= 66:
        parts.append("sourceid_guess=%d" % u16(data, 62))
    if len(data) >= 90:
        parts.append("flags_guess=0x%x" % u32(data, 86))
    print("[guess] " + " ".join(parts))


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    if sys.platform != "linux":
        print("cp_p2_x11_pinch: Linux/X11 probe only; refusing to run"
              " on %s" % sys.platform)
        return 1

    try:
        disp = xdisplay.Display()
    except Exception as exc:
        print("cp_p2_x11_pinch: cannot open X display: %s" % exc)
        return 1

    print_environment(disp)

    # Keep asynchronous X errors non-fatal and visible.
    def x_error_handler(err, request):
        print("[x-error] %r (request=%r)" % (err, request))
    disp.set_error_handler(x_error_handler)

    if not disp.has_extension(xinput.extname):
        print("VERDICT: unavailable (no XInputExtension)")
        disp.close()
        return 0
    if not disp.has_extension(ge.extname):
        # Without XGE, GenericEvents (type 35) cannot be parsed by
        # python-xlib; XI2 cannot exist without it either.
        print("VERDICT: unavailable (no Generic Event Extension)")
        disp.close()
        return 0

    xi_opcode = disp.display.get_extension_major(xinput.extname)
    print("XInputExtension major opcode = %d" % xi_opcode)

    try:
        major, minor = xi_query_version_24(disp)
    except Exception as exc:
        print("XIQueryVersion(2.4) failed: %r" % exc)
        print("VERDICT: unavailable (xi handshake error)")
        disp.close()
        return 0
    print("XIQueryVersion: requested 2.4, server answered %d.%d"
          % (major, minor))
    if (major, minor) < (2, 4):
        # A pre-2.4 server cannot emit gesture events; that is itself a
        # valid probe verdict for this session.
        print("VERDICT: unavailable (xi %d.%d)" % (major, minor))
        disp.close()
        return 0

    screen = disp.screen()
    orange = alloc_pixel(screen, 65535, 42405, 0, screen.white_pixel)
    cyan = alloc_pixel(screen, 0, 55000, 65535, screen.white_pixel)

    # (a) normal managed window, (b) override-redirect window beside it.
    # The app's overlay windows are override-redirect on X11, so gesture
    # delivery must be probed on both window kinds.
    normal_win, normal_gc = make_window(
        disp, screen, 100, 100, orange,
        "CP-P2 pinch here (normal)", override=False)
    override_win, override_gc = make_window(
        disp, screen, 100 + WIN_W + 40, 100, cyan,
        "CP-P2 pinch here (override)", override=True)
    disp.sync()

    win_labels = {
        normal_win.id: "normal",
        override_win.id: "override",
    }
    print("normal window   id=0x%x (orange, managed)" % normal_win.id)
    print("override window id=0x%x (cyan, override-redirect)"
          % override_win.id)

    # Pinch gesture bits on BOTH windows for XIAllMasterDevices (=1).
    pinch_bits = (
        XI_GESTURE_PINCH_BEGIN,
        XI_GESTURE_PINCH_UPDATE,
        XI_GESTURE_PINCH_END,
    )
    # Sanity bits only on the normal window: if plain XI motion/enter/
    # leave shows up there, XI event delivery works at all in this
    # session and a missing pinch is meaningful.
    sanity_bits = (xinput.Motion, xinput.Enter, xinput.Leave)

    xi_select_events(disp, normal_win, xinput.AllMasterDevices,
                     pinch_bits + sanity_bits)
    xi_select_events(disp, override_win, xinput.AllMasterDevices,
                     pinch_bits)
    disp.sync()
    print("XISelectEvents done: pinch bits %s on both windows"
          " (deviceid=%d XIAllMasterDevices), plus motion/enter/leave"
          " on the normal window" % (list(pinch_bits),
                                     xinput.AllMasterDevices))
    print()
    print("=== operator instructions ===")
    print("1. Hover the pointer over the ORANGE window; pinch on the")
    print("   touchpad (two fingers, spread/contract).")
    print("2. Do the same over the CYAN override-redirect window.")
    print("3. Also two-finger SCROLL over the orange window: that is the")
    print("   control - XI Motion lines prove plain XI delivery works.")
    print("4. Run this once under Xorg and once under a Wayland session")
    print("   (XWayland); record both outputs.")
    print("5. Ctrl+C to quit.")
    print()

    signal.signal(signal.SIGINT, _on_sigint)

    saw_motion = False
    saw_pinch = False

    def handle_event(e):
        nonlocal saw_motion, saw_pinch
        if e.type == X.Expose:
            # Keep both windows solid bright so the operator can see them.
            if e.window.id == normal_win.id:
                repaint(normal_win, normal_gc)
            elif e.window.id == override_win.id:
                repaint(override_win, override_gc)
            return
        if e.type != GENERIC_EVENT_CODE:
            return  # core noise (MapNotify, ConfigureNotify, ...)
        if getattr(e, "extension", None) != xi_opcode:
            print("[generic] non-XInput GenericEvent extension=%r"
                  % getattr(e, "extension", None))
            return

        evtype = e.evtype
        data = e.data
        name = EVTYPE_NAMES.get(evtype, "evtype%d" % evtype)

        if evtype in GESTURE_EVTYPES and isinstance(data, (bytes, bytearray)):
            saw_pinch = True
            win_id = guess_event_window(data)
            label = win_labels.get(win_id, "unknown(0x%x)" % (win_id or 0))
            header = getattr(e, "_binary", b"")
            dump_gesture_event(evtype, bytes(header), bytes(data), label)
            return

        # Non-gesture XI events: one short line each.
        if isinstance(data, (bytes, bytearray)):
            win_id = guess_event_window(bytes(data))
            label = win_labels.get(win_id, "?")
            print("[xi] evtype=%d (%s) win=%s len=%d"
                  % (evtype, name, label, len(data)))
        else:
            # python-xlib registered a parser for this evtype (e.g.
            # Motion via DeviceEventData) - data is a parsed object.
            win_id = getattr(getattr(data, "event", None), "id",
                             getattr(data, "event", None))
            label = win_labels.get(win_id, "?")
            extra = ""
            if evtype == xinput.Motion:
                saw_motion = True
                try:
                    extra = " event_x=%.1f event_y=%.1f" % (
                        data.event_x, data.event_y)
                except Exception:
                    pass
            print("[xi] evtype=%d (%s) win=%s%s"
                  % (evtype, name, label, extra))

    # Event loop: select() on the display fd with a short timeout so the
    # SIGINT flag is honored promptly; drain all pending events per tick.
    fd = disp.fileno()
    try:
        while not _stop:
            try:
                rlist, _, _ = select.select([fd], [], [], 0.5)
            except InterruptedError:
                continue
            if not rlist:
                continue
            while disp.pending_events():
                handle_event(disp.next_event())
    except KeyboardInterrupt:
        pass

    print()
    print("=== summary ===")
    print("XI motion/enter/leave sanity events seen: %s" % saw_motion)
    print("pinch gesture events seen:                %s" % saw_pinch)
    if saw_pinch:
        print("VERDICT: pinch gesture events ARE delivered in this session"
              " (raw dumps above are fixture material)")
    else:
        print("VERDICT: no pinch gesture events observed"
              " (server negotiated %d.%d; check the control Motion lines"
              " before concluding non-delivery)" % (major, minor))

    try:
        normal_win.destroy()
        override_win.destroy()
        disp.sync()
    except Exception:
        pass
    disp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
