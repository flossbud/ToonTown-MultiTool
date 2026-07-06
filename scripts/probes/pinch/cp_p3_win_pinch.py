r"""CP-P3 probe (pinch zoom): which rung of the Windows delivery ladder does a
precision-touchpad pinch arrive on - and can INPUT PROVENANCE tell it apart
from a real mouse Ctrl+wheel?

Windows can deliver a touchpad pinch as WM_GESTURE (GID_ZOOM), as WM_POINTER*
traffic, as WM_TOUCH, or synthesized as a legacy Ctrl + WM_MOUSEWHEEL. The
last one is the dangerous rung: it is byte-identical to a user physically
holding Ctrl and rolling a mouse wheel UNLESS provenance is checked. This
probe opens a plain white 400x400 window, enables every rung it can
(SetGestureConfig GC_ZOOM, EnableMouseInPointer, RegisterTouchWindow), then
logs one tagged line per message. For WM_MOUSEWHEEL it calls
GetCurrentInputMessageSource inside the handler and prints both fields
(deviceType + originId) decoded, so a pinch-synthesized wheel
(IMDT_TOUCHPAD / non-IMO_HARDWARE) is distinguishable from a hardware mouse
wheel (IMDT_MOUSE + IMO_HARDWARE).

Pure ctypes + stdlib; no third-party imports. Windows-only at runtime, but
importable anywhere (all user32/kernel32/gdi32 access sits behind a
sys.platform == "win32" guard).

Operator steps:

  1. run `python scripts\probes\pinch\cp_p3_win_pinch.py` from the repo root
     on the winbox
  2. precision-touchpad PINCH over the window (both directions)
  3. touchpad two-finger SCROLL over it
  4. REAL MOUSE Ctrl+wheel over it - the negative provenance test, REQUIRED
  5. touchscreen pinch if the box has one
  6. close the window or Ctrl+C

Every line of output is evidence - copy the FULL stdout back.
"""
import ctypes
import platform
import sys
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Constants (plain ints; safe to define on any platform).
# ---------------------------------------------------------------------------

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_GESTURE = 0x0119
WM_GESTURENOTIFY = 0x011A
WM_MOUSEWHEEL = 0x020A
WM_TOUCH = 0x0240
WM_POINTERUPDATE = 0x0245
WM_POINTERDOWN = 0x0246
WM_POINTERUP = 0x0247
WM_POINTERWHEEL = 0x024E

POINTER_MSG_NAMES = {
    WM_POINTERUPDATE: "WM_POINTERUPDATE",
    WM_POINTERDOWN: "WM_POINTERDOWN",
    WM_POINTERUP: "WM_POINTERUP",
    WM_POINTERWHEEL: "WM_POINTERWHEEL",
}

# GESTUREINFO.dwID values.
GID_NAMES = {
    1: "GID_BEGIN",
    2: "GID_END",
    3: "GID_ZOOM",
    4: "GID_PAN",
    5: "GID_ROTATE",
    6: "GID_TWOFINGERTAP",
    7: "GID_PRESSANDTAP",
}
GID_ZOOM = 3
GC_ZOOM = 0x00000001

# GetPointerType -> POINTER_INPUT_TYPE.
PT_NAMES = {
    1: "PT_POINTER",
    2: "PT_TOUCH",
    3: "PT_PEN",
    4: "PT_MOUSE",
    5: "PT_TOUCHPAD",
}

# INPUT_MESSAGE_SOURCE.deviceType (INPUT_MESSAGE_DEVICE_TYPE).
IMDT_NAMES = {
    0: "IMDT_UNAVAILABLE",
    1: "IMDT_KEYBOARD",
    2: "IMDT_MOUSE",
    4: "IMDT_TOUCH",
    8: "IMDT_PEN",
    64: "IMDT_TOUCHPAD",
}

# INPUT_MESSAGE_SOURCE.originId (INPUT_MESSAGE_ORIGIN_ID).
IMO_NAMES = {
    0: "IMO_UNAVAILABLE",
    1: "IMO_HARDWARE",
    2: "IMO_INJECTED",
    4: "IMO_SYSTEM",
}

MK_CONTROL = 0x0008

CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
CW_USEDEFAULT = -0x80000000  # 0x80000000 expressed as a signed c_int
SW_SHOW = 5
WHITE_BRUSH = 0
IDC_ARROW = 32512

WINDOW_CLASS_NAME = "CPP3PinchProbe"
WINDOW_TITLE = "CP-P3 pinch here"


def log(line):
    # Flush every line: if the window or console dies mid-gesture, the
    # already-printed evidence must survive.
    print(line, flush=True)


# ---------------------------------------------------------------------------
# Structs (pure ctypes; safe to define on any platform).
# ---------------------------------------------------------------------------


class POINTS(ctypes.Structure):
    _fields_ = [("x", wintypes.SHORT), ("y", wintypes.SHORT)]


class GESTURECONFIG(ctypes.Structure):
    _fields_ = [
        ("dwID", wintypes.DWORD),
        ("dwWant", wintypes.DWORD),
        ("dwBlock", wintypes.DWORD),
    ]


class GESTUREINFO(ctypes.Structure):
    # Natural (MSVC-default) alignment, same as winuser.h; ctypes matches it.
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwFlags", wintypes.DWORD),
        ("dwID", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
        ("ptsLocation", POINTS),
        ("dwInstanceID", wintypes.DWORD),
        ("dwSequenceID", wintypes.DWORD),
        ("ullArguments", ctypes.c_ulonglong),
        ("cbExtraArgs", wintypes.UINT),
    ]


class INPUT_MESSAGE_SOURCE(ctypes.Structure):
    # Two C enums (32-bit each): deviceType, originId.
    _fields_ = [
        ("deviceType", ctypes.c_uint32),
        ("originId", ctypes.c_uint32),
    ]


# ---------------------------------------------------------------------------
# Windows-only plumbing. Everything that touches user32/kernel32/gdi32 (or
# WINFUNCTYPE, which only exists on Windows) lives behind this guard so the
# module stays importable-in-theory on any platform.
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    # use_last_error=True makes ctypes snapshot GetLastError per call, so
    # ctypes.get_last_error() is reliable even if Python touches the OS
    # between the failing call and the read.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    # LRESULT/LONG_PTR: pointer-sized signed int on both 32- and 64-bit.
    LRESULT = ctypes.c_ssize_t

    WNDPROCTYPE = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROCTYPE),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    # Explicit prototypes: without restype=HWND/LRESULT the ctypes default of
    # c_int truncates 64-bit handles and return values.
    _user32.DefWindowProcW.restype = LRESULT
    _user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UpdateWindow.argtypes = [wintypes.HWND]
    _user32.GetMessageW.restype = ctypes.c_int  # BOOL, but -1 on error
    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
    ]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.LoadCursorW.restype = wintypes.HANDLE
    _user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    _user32.SetGestureConfig.restype = wintypes.BOOL
    _user32.SetGestureConfig.argtypes = [
        wintypes.HWND, wintypes.DWORD, wintypes.UINT,
        ctypes.POINTER(GESTURECONFIG), wintypes.UINT,
    ]
    _user32.GetGestureInfo.restype = wintypes.BOOL
    _user32.GetGestureInfo.argtypes = [
        wintypes.LPVOID, ctypes.POINTER(GESTUREINFO),
    ]
    _user32.CloseGestureInfoHandle.restype = wintypes.BOOL
    _user32.CloseGestureInfoHandle.argtypes = [wintypes.LPVOID]
    _user32.RegisterTouchWindow.restype = wintypes.BOOL
    _user32.RegisterTouchWindow.argtypes = [wintypes.HWND, wintypes.ULONG]
    _gdi32.GetStockObject.restype = wintypes.HGDIOBJ
    _gdi32.GetStockObject.argtypes = [ctypes.c_int]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
    _kernel32.SetConsoleCtrlHandler.argtypes = [PHANDLER_ROUTINE, wintypes.BOOL]

    def _optional_export(dll, name, restype, argtypes):
        # Win8+ exports: absence (older Windows) is evidence, not a crash.
        try:
            fn = getattr(dll, name)
        except AttributeError:
            return None
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    _EnableMouseInPointer = _optional_export(
        _user32, "EnableMouseInPointer", wintypes.BOOL, [wintypes.BOOL]
    )
    _GetPointerType = _optional_export(
        _user32, "GetPointerType", wintypes.BOOL,
        [wintypes.UINT, ctypes.POINTER(wintypes.DWORD)],
    )
    _GetCurrentInputMessageSource = _optional_export(
        _user32, "GetCurrentInputMessageSource", wintypes.BOOL,
        [ctypes.POINTER(INPUT_MESSAGE_SOURCE)],
    )

    # Shared with the console ctrl handler (which runs on its own thread).
    _state = {"hwnd": None}

    # ---------------- message handlers ----------------

    def _on_gesture(lparam):
        gi = GESTUREINFO()
        # cbSize MUST be set before the call: GetGestureInfo validates it and
        # fails with ERROR_INVALID_PARAMETER on a zeroed struct.
        gi.cbSize = ctypes.sizeof(GESTUREINFO)
        handle = ctypes.c_void_p(lparam)
        if _user32.GetGestureInfo(handle, ctypes.byref(gi)):
            gid = GID_NAMES.get(gi.dwID, "GID_%d" % gi.dwID)
            log(
                "[gesture] id=%s(%d) flags=0x%x args=%d loc=(%d,%d)"
                % (
                    gid, gi.dwID, gi.dwFlags, gi.ullArguments,
                    gi.ptsLocation.x, gi.ptsLocation.y,
                )
            )
            # Docs say close XOR forward-to-DefWindowProc; this probe logs and
            # closes, then still forwards (per the ladder recipe) so default
            # gesture plumbing keeps flowing. The worst case is a benign
            # failed re-close inside DefWindowProc.
            _user32.CloseGestureInfoHandle(handle)
        else:
            log("[gesture] GetGestureInfo FAILED gle=%d" % ctypes.get_last_error())

    def _on_pointer(msg, wparam):
        pointer_id = wparam & 0xFFFF  # LOWORD(wParam) == pointerId
        if _GetPointerType is None:
            type_name = "unavailable(no GetPointerType export)"
        else:
            ptype = wintypes.DWORD(0)
            if _GetPointerType(pointer_id, ctypes.byref(ptype)):
                type_name = PT_NAMES.get(ptype.value, "PT_%d" % ptype.value)
            else:
                type_name = "FAILED(gle=%d)" % ctypes.get_last_error()
        log("[pointer] msg=%s type=%s id=%d" % (POINTER_MSG_NAMES[msg], type_name, pointer_id))

    def _on_wheel(wparam):
        # GET_WHEEL_DELTA_WPARAM: signed HIWORD.
        delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
        ctrl = bool(wparam & MK_CONTROL)
        # Provenance MUST be read inside the handler: the result reflects the
        # message currently being processed by this thread.
        if _GetCurrentInputMessageSource is None:
            src = "unavailable(no GetCurrentInputMessageSource export)"
        else:
            ims = INPUT_MESSAGE_SOURCE()
            if _GetCurrentInputMessageSource(ctypes.byref(ims)):
                dev = IMDT_NAMES.get(ims.deviceType, "IMDT_0x%x" % ims.deviceType)
                origin = IMO_NAMES.get(ims.originId, "IMO_%d" % ims.originId)
                src = "deviceType=%s(0x%x) originId=%s(%d)" % (
                    dev, ims.deviceType, origin, ims.originId,
                )
            else:
                src = "FAILED(gle=%d)" % ctypes.get_last_error()
        log("[wheel] delta=%d ctrl=%s src=%s" % (delta, ctrl, src))

    def _py_wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_GESTURE:
                _on_gesture(lparam)
            elif msg == WM_GESTURENOTIFY:
                log("[gesturenotify] WM_GESTURENOTIFY (gesture sequence incoming)")
            elif msg in POINTER_MSG_NAMES:
                _on_pointer(msg, wparam)
            elif msg == WM_MOUSEWHEEL:
                _on_wheel(wparam)
            elif msg == WM_TOUCH:
                # LOWORD(wParam) = number of touch points. Contact details
                # would need GetTouchInputInfo; count alone places the rung.
                log("[touch] count=%d" % (wparam & 0xFFFF))
            elif msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
        except Exception as exc:  # never let an exception escape the thunk
            log("[error] wndproc: %r" % (exc,))
        # Everything (including logged WM_GESTURE / WM_POINTER*) falls through
        # to DefWindowProc. For WM_POINTER* that matters: unhandled pointer
        # messages make the system synthesize the legacy mouse messages, so
        # even with EnableMouseInPointer on, rung 4 (WM_MOUSEWHEEL provenance)
        # still logs.
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # Module-level references to both ctypes thunks. Classic landmine: the
    # window (or console) keeps calling the native thunk long after any local
    # variable dies; if Python GCs the callback object, the next message is a
    # call through freed memory and the process dies.
    _WNDPROC = WNDPROCTYPE(_py_wndproc)

    def _py_ctrl_handler(ctrl_type):
        # Runs on a console-spawned thread. PostQuitMessage is thread-affine
        # (would quit the WRONG thread here), PostMessageW is cross-thread
        # safe: route shutdown through WM_CLOSE -> DestroyWindow ->
        # WM_DESTROY -> PostQuitMessage on the GUI thread.
        hwnd = _state["hwnd"]
        if hwnd:
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True

    _CTRL_HANDLER = PHANDLER_ROUTINE(_py_ctrl_handler)

    # ---------------- probe body ----------------

    def run_probe():
        hinstance = _kernel32.GetModuleHandleW(None)

        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = _WNDPROC
        wc.hInstance = hinstance
        wc.hCursor = _user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = _gdi32.GetStockObject(WHITE_BRUSH)
        wc.lpszClassName = WINDOW_CLASS_NAME
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            log("[cp-p3] RegisterClassW FAILED gle=%d" % ctypes.get_last_error())
            return 1

        hwnd = _user32.CreateWindowExW(
            0, WINDOW_CLASS_NAME, WINDOW_TITLE,
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT, CW_USEDEFAULT, 400, 400,
            None, None, hinstance, None,
        )
        if not hwnd:
            log("[cp-p3] CreateWindowExW FAILED gle=%d" % ctypes.get_last_error())
            return 1
        _state["hwnd"] = hwnd
        _user32.ShowWindow(hwnd, SW_SHOW)
        _user32.UpdateWindow(hwnd)

        # Rung 1: ask for GID_ZOOM. SetGestureConfig persists on the window,
        # so one call before the loop covers every gesture sequence.
        cfg = GESTURECONFIG(GID_ZOOM, GC_ZOOM, 0)
        if _user32.SetGestureConfig(hwnd, 0, 1, ctypes.byref(cfg),
                                    ctypes.sizeof(GESTURECONFIG)):
            log("[setup] SetGestureConfig(GID_ZOOM, GC_ZOOM) ok")
        else:
            log("[setup] SetGestureConfig(GID_ZOOM, GC_ZOOM) FAILED gle=%d"
                % ctypes.get_last_error())

        # Rung 2: route mouse input through the pointer stack too (process-
        # wide, one-shot, irreversible). A failure here is data, not an error.
        if _EnableMouseInPointer is None:
            log("[setup] EnableMouseInPointer unavailable (export missing)")
        elif _EnableMouseInPointer(True):
            log("[setup] EnableMouseInPointer(TRUE) ok")
        else:
            log("[setup] EnableMouseInPointer(TRUE) FAILED gle=%d"
                " (failure is data, not an error)" % ctypes.get_last_error())

        # Rung 3: raw touch. Note the documented trade: a touch-registered
        # window receives WM_TOUCH INSTEAD of WM_GESTURE for touchscreen
        # contact - that swap is itself ladder evidence (touchPAD pinch does
        # not ride the touch-window path, touchSCREEN pinch does).
        if _user32.RegisterTouchWindow(hwnd, 0):
            log("[setup] RegisterTouchWindow(hwnd, 0) ok")
        else:
            log("[setup] RegisterTouchWindow(hwnd, 0) FAILED gle=%d"
                " (failure is data, not an error)" % ctypes.get_last_error())

        if not _kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, True):
            log("[setup] SetConsoleCtrlHandler FAILED gle=%d (Ctrl+C may kill"
                " the process hard; use the window close button)"
                % ctypes.get_last_error())

        log('[cp-p3] window "%s" up - pinch / scroll / Ctrl+wheel over it;'
            " Ctrl+C or close the window to exit" % WINDOW_TITLE)

        msg = wintypes.MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:  # WM_QUIT
                break
            if ret == -1:
                log("[cp-p3] GetMessageW FAILED gle=%d" % ctypes.get_last_error())
                return 1
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        log("[cp-p3] exiting")
        return 0


def main():
    log("[cp-p3] python=%s windows=%s" % (platform.python_version(), platform.platform()))
    if sys.platform != "win32":
        log("[cp-p3] not win32 - this probe only runs on Windows")
        return 1
    return run_probe()


if __name__ == "__main__":
    sys.exit(main())
