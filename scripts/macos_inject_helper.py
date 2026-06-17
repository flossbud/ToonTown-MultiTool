#!/usr/bin/env python3
"""Platform-binary injection helper (THROWAWAY prototype, gated by
TTMT_MACOS_INJECT_HELPER). Runs under the system /usr/bin/python3 (an Apple
*platform binary*, CS_PLATFORM_BINARY=True), holds the PRODUCTION
utils.macos_mouse_delivery.MacOSMouseDelivery, and answers JSON-line RPCs from
the app over stdin -> stdout. Tests whether routing the SkyLight SLEventPostToPid
poster through a platform-binary child actuates a background toon.

stdout is JSON-ONLY. The engine's diagnostics use print() (-> fd 1), so we move
fd 1 to stderr at startup and keep a private dup of the real stdout for replies.
"""
import ctypes
import json
import os
import sys

# ---- stdout discipline (do this FIRST, before any import that might print) ----
# Save the real stdout pipe (to the parent) on a private fd, then point fd 1 at
# fd 2 (stderr/logfile) so ANY print()/C-level stdout from the engine or pyobjc
# cannot corrupt the JSON-RPC channel.
_reply = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)

# repo root is the spawn cwd; make `utils` importable.
sys.path.insert(0, os.getcwd())


def log(msg):
    print(f"[inject-helper] {msg}", file=sys.stderr, flush=True)


def _platform_binary():
    try:
        libc = ctypes.CDLL(None)
        f = ctypes.c_uint32(0)
        libc.csops(os.getpid(), 0, ctypes.byref(f), ctypes.sizeof(f))
        return bool(f.value & 0x04000000)
    except Exception as e:
        return f"err:{e}"


def reply(obj):
    _reply.write(json.dumps(obj) + "\n")
    _reply.flush()


log(f"start sys.executable={sys.executable} ppid={os.getppid()} cwd={os.getcwd()}")
log(f"CS_PLATFORM_BINARY={_platform_binary()}")
try:
    import Quartz
    log(f"CGPreflightPostEventAccess={Quartz.CGPreflightPostEventAccess()}")
except Exception as e:
    log(f"preflight-error {e}")

from utils import macos_mouse_delivery as mmd
log(f"engine module={mmd.__file__}")
eng = mmd.MacOSMouseDelivery()
log(f"engine.available={eng.available}")


def handle(req):
    op = req["op"]
    if op == "ping":
        return {"ok": True, "available": bool(eng.available)}
    if op == "resolve_psn":
        psn = eng.resolve_psn(int(req["wid"]))
        return {"ok": True, "psn": psn.hex() if psn else ""}
    if op == "resolve_owner":
        return {"ok": True, "owner": eng.resolve_owner(int(req["wid"]))}
    if op in ("press", "release", "motion"):
        pid, wid = int(req["pid"]), int(req["wid"])
        psn = bytes.fromhex(req["psn"]) if req.get("psn") else None
        win = (float(req["win"][0]), float(req["win"][1]))
        scr = (float(req["screen"][0]), float(req["screen"][1]))
        log(f"{op} pid={pid} wid={wid} psn={'set' if psn else 'NONE'} win={win} scr={scr}")
        if op == "press":
            r = eng.press(pid, wid, psn, win, scr)
        elif op == "release":
            r = eng.release(pid, wid, psn, win, scr)
        else:
            r = eng.motion(pid, wid, psn, win, scr, dragging=bool(req.get("dragging")))
        return {"ok": True, "result": bool(r)}
    return {"ok": False, "error": f"unknown op {op}"}


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        resp = handle(req)
        # motion (hover/drag) is FIRE-AND-FORGET: no reply, so the parent never
        # blocks on the 60Hz hover stream. press/release/resolve/ping still reply.
        if req.get("op") != "motion":
            reply(resp)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            reply({"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass

log("stdin closed; exiting")
