"""Whether THIS process is an Apple platform binary (CS_PLATFORM_BINARY). The private
SkyLight SLEventPostToPid mouse path only actuates from a platform binary, so this is the
real predicate for in-process vs helper delivery. Cached once per process."""
import ctypes
import os

CS_PLATFORM_BINARY = 0x04000000
_CS_OPS_STATUS = 0
_cached = None


def decode(flags: int) -> bool:
    return bool(int(flags) & CS_PLATFORM_BINARY)


def csflags() -> int:
    libc = ctypes.CDLL(None)
    out = ctypes.c_uint32(0)
    libc.csops(os.getpid(), _CS_OPS_STATUS, ctypes.byref(out), ctypes.sizeof(out))
    return int(out.value)


def is_platform_binary() -> bool:
    global _cached
    if _cached is None:
        try:
            _cached = decode(csflags())
        except Exception:
            _cached = False  # fail safe: assume non-platform -> use the helper
    return _cached
