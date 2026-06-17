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
    libc = ctypes.CDLL(None, use_errno=True)
    # Pin the ABI so usersize is passed as a 64-bit size_t (not a default C int)
    # and the return code is read as int. csops(2) returns 0 on success and -1
    # with errno set on failure; trusting out.value without checking rc would
    # silently read a stale 0 on error.
    libc.csops.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t]
    libc.csops.restype = ctypes.c_int
    out = ctypes.c_uint32(0)
    rc = libc.csops(os.getpid(), _CS_OPS_STATUS, ctypes.byref(out), ctypes.sizeof(out))
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err) if err else "csops failed")
    return int(out.value)


def is_platform_binary() -> bool:
    global _cached
    if _cached is None:
        try:
            _cached = decode(csflags())
        except Exception:
            _cached = False  # fail safe: assume non-platform -> use the helper
    return _cached
