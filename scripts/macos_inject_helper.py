#!/usr/bin/env python3
"""Self-contained platform-binary injection helper for macOS Click Sync.

Runs under the system /usr/bin/python3 (an Apple *platform binary*,
CS_PLATFORM_BINARY=True) because the private SkyLight SLEventPostToPid mouse
path only actuates from a platform-binary process. It holds the pyobjc-free
delivery engine (macos_mouse_delivery.MacOSMouseDelivery) and answers
JSON-line RPCs from the app over stdin -> stdout.

Packaging: the .app ships this file AND macos_mouse_delivery.py FLAT in the
same directory (Contents/Resources/ttmt_inject/), so the engine is imported by
its own location, NOT via `from utils import`. A source-layout fallback covers
running straight from the repo (scripts/ + utils/).

stdout is JSON-ONLY. The engine's diagnostics use print() (-> fd 1), so we move
fd 1 to stderr at startup and keep a private dup of the real stdout for replies.
The parent captures fd 2 (stderr) to its helper logfile.
"""
import os  # noqa: E402  (only os, needed for the fd dance, precedes the redirect)

# ---- stdout discipline (do this FIRST, before any import that might print) ----
# Save the real stdout pipe (to the parent) on a private fd, then point fd 1 at
# fd 2 (stderr/logfile) so ANY print()/C-level stdout from a LATER import or the
# engine cannot corrupt the JSON-RPC channel. Only `os` is imported above this
# point, and importing os does not write to stdout.
_reply = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)

import ctypes  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402

# ---- own-location import (flat .app layout), with a repo-source fallback ------
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
try:
    # Flat bundle: macos_mouse_delivery.py ships beside this helper.
    import macos_mouse_delivery as mmd  # noqa: E402
except ImportError:
    # Repo source layout: helper lives in scripts/, engine in utils/.
    sys.path.insert(0, os.path.dirname(_HERE))
    from utils import macos_mouse_delivery as mmd  # noqa: E402

PROTOCOL = 1

# Ops that send a reply line back to the parent. The post ops (press/release/
# motion) are FIRE-AND-FORGET (no reply) so the parent never blocks on a post.
REPLYING_OPS = ("hello", "ping", "resolve_psn", "resolve_owner")


def log(msg):
    print(f"[inject-helper] {msg}", file=sys.stderr, flush=True)


def reply(obj):
    _reply.write(json.dumps(obj) + "\n")
    _reply.flush()


def _csops_platform_binary():
    """Whether THIS process is an Apple platform binary (the actuation predicate).
    Inlined (the flat bundle ships ONLY this helper + the delivery module)."""
    try:
        libc = ctypes.CDLL(None)
        f = ctypes.c_uint32(0)
        libc.csops(os.getpid(), 0, ctypes.byref(f), ctypes.sizeof(f))
        return bool(f.value & 0x04000000)
    except Exception:
        return None


def _selftest():
    """Handshake diagnostics: protocol, platform-binary status, and live proof the
    SkyLight framework + the pure-ctypes ObjC bridge + the post-event preflight all
    initialise in THIS process. Exercising the bridge here makes an objc-init failure
    detectable by the parent before any real injection is attempted."""
    sky = mmd._load_skylight()
    objc_ok = False
    # Wrap the bridge exercise in an autorelease pool (same as the engine's real post
    # paths) so the autoreleased NSEvent doesn't leak / log a "no pool in place"
    # warning to the helper log under the run-loop-less CLI python.
    pool = mmd._push_autorelease_pool()
    try:
        objc_ok = bool(mmd._build_ns_cgevent(1, 1, 0))  # exercise the ObjC bridge
    except Exception:
        objc_ok = False
    finally:
        mmd._pop_autorelease_pool(pool)
    pf = None
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        pf = bool(cg.CGPreflightPostEventAccess())
    except Exception:
        pf = None
    return {"protocol": PROTOCOL, "platform_binary": _csops_platform_binary(),
            "skylight_ok": sky is not None, "objc_ok": objc_ok,
            "preflight_post_access": pf}


log(f"start sys.executable={sys.executable} ppid={os.getppid()} cwd={os.getcwd()}")
log(f"engine module={mmd.__file__}")
eng = mmd.MacOSMouseDelivery()
log(f"engine.available={eng.available}")


def handle(req):
    op = req["op"]
    if op == "hello":
        return {"ok": True, **_selftest()}
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
    req = None
    try:
        req = json.loads(line)
        resp = handle(req)
        # Only the REPLYING_OPS write a reply line; post ops stay fire-and-forget so
        # the parent never blocks on a post. This keeps the channel in sync: the proxy
        # reads a reply ONLY for ops the helper actually replies to. Echo any
        # correlation id the request carried back on the reply.
        if req.get("op") in REPLYING_OPS:
            if "id" in req:
                resp["id"] = req["id"]
            reply(resp)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        # Emit an error reply ONLY for an op the parent is actually awaiting. For a
        # fire-and-forget post op (failing in arg-parse before the engine's own guards)
        # or an unparseable / non-dict line, stay SILENT on stdout: the parent's
        # _send_noreply never reads, so a stray line would be misread as the NEXT
        # replying op's reply and desync the channel. This mirrors the success path's
        # "write a line only for REPLYING_OPS" invariant.
        op = req.get("op") if isinstance(req, dict) else None
        if op in REPLYING_OPS:
            try:
                err = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                if "id" in req:
                    err["id"] = req["id"]
                reply(err)
            except Exception:
                pass

log("stdin closed; exiting")
