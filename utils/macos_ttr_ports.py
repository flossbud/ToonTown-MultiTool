"""macOS port->host-PID mapping for ttr_api. Global net_connections is
AccessDenied without root on macOS; per-PID Process.net_connections works
without sudo (proven in the Phase-0 spike)."""
from __future__ import annotations


def _listen_ports_for_pid(pid: int) -> list:
    """Loopback LISTEN ports for one PID (per-PID; no sudo). [] on error."""
    import psutil
    try:
        proc = psutil.Process(pid)
        getter = getattr(proc, "net_connections", None) or proc.connections
        ports = []
        for c in getter(kind="inet"):
            if c.status != "LISTEN" or not c.laddr:
                continue
            ip = getattr(c.laddr, "ip", None)
            if isinstance(ip, str) and (ip == "::1" or ip.startswith("127.")):
                ports.append(int(c.laddr.port))
        return ports
    except Exception:
        return []


def port_to_host_pid(pids, lo: int, hi: int) -> dict:
    """{port: pid} for loopback LISTEN ports in [lo, hi] owned by the given pids."""
    out = {}
    for pid in pids:
        for port in _listen_ports_for_pid(pid):
            if lo <= port <= hi:
                out[port] = pid
    return out
