#!/usr/bin/env python3
"""Phase-0 spike (THROWAWAY): prove a PURE-CTYPES (no PyObjC) objc_msgSend NSEvent
actuates a background TTR toon via SkyLight, and answer the TCC attribution question.

The inject path imports NO PyObjC. Run it under `/usr/bin/python3 -s` with a scrubbed
env so the operator's --user PyObjC cannot leak in.

Subcommands:
  provenance      pure ctypes: interpreter, csops bits, post-event preflight, AX-trusted
  request-access  pure ctypes: call CGRequestPostEventAccess() and print the result
  resolve         LAZY pyobjc (operator tooling): print inject args for a window id
  inject          pure ctypes: post press+release (or hover) to a background window
"""
import argparse
import ctypes
import os
import sys

CS_PLATFORM_BINARY = 0x04000000
CS_RUNTIME = 0x00010000
CS_OPS_STATUS = 0  # csops op: get status flags


def decode_csflags(flags: int) -> dict:
    return {
        "platform_binary": bool(flags & CS_PLATFORM_BINARY),
        "runtime": bool(flags & CS_RUNTIME),
    }


def csflags_for_pid(pid: int) -> int:
    libc = ctypes.CDLL(None)
    out = ctypes.c_uint32(0)
    libc.csops(int(pid), CS_OPS_STATUS, ctypes.byref(out), ctypes.sizeof(out))
    return int(out.value)


def _cg():
    # CGPreflightPostEventAccess / CGRequestPostEventAccess live in CoreGraphics.
    return ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


def preflight_post_access():
    try:
        fn = _cg().CGPreflightPostEventAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def ax_is_trusted():
    try:
        appserv = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        fn = appserv.AXIsProcessTrusted
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def cmd_provenance(args) -> int:
    flags = csflags_for_pid(os.getpid())
    info = {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "uname": os.uname().release,
        "machine": os.uname().machine,
        "csflags": hex(flags),
        **decode_csflags(flags),
        "preflight_post_access": preflight_post_access(),
        "ax_is_trusted": ax_is_trusted(),
    }
    for k, v in info.items():
        print(f"{k}={v}")
    return 0


def cmd_request_access(args) -> int:
    """Trigger the OS Accessibility (post-event) prompt for THIS process identity and
    print the result. On a clean account this reveals whether the prompt attributes to
    the app or to Python (spec 6.7)."""
    try:
        fn = _cg().CGRequestPostEventAccess
        fn.restype = ctypes.c_bool
        granted = bool(fn())
    except Exception as e:
        print(f"request-access error: {type(e).__name__}: {e}")
        return 1
    print(f"request_post_access_granted={granted}")
    print(f"preflight_after={preflight_post_access()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase-0 pure-ctypes click-sync spike")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("provenance")
    sub.add_parser("request-access")
    pr = sub.add_parser("resolve")
    pr.add_argument("--wid", type=int, required=True)
    pr.add_argument("--frac-x", type=float, default=0.5)
    pr.add_argument("--frac-y", type=float, default=0.5)
    pi = sub.add_parser("inject")
    pi.add_argument("--pid", type=int, required=True)
    pi.add_argument("--wid", type=int, required=True)
    pi.add_argument("--win-x", type=float, required=True)
    pi.add_argument("--win-y", type=float, required=True)
    pi.add_argument("--screen-x", type=float, required=True)
    pi.add_argument("--screen-y", type=float, required=True)
    pi.add_argument("--kind", choices=["click", "hover"], default="click")
    pi.add_argument("--countdown", type=int, default=0)
    pi.add_argument("--repeat", type=int, default=1)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "provenance":
        return cmd_provenance(args)
    if args.cmd == "request-access":
        return cmd_request_access(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)          # Task 3
    if args.cmd == "inject":
        return cmd_inject(args)           # Task 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
