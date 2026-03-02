"""
TTR Local (Companion App) API client.

Scans ports 1547-1552 for active TTR instances and fetches toon info.
Slot assignment is based on window X position (left to right) to match
the order used by input_service, not launch order.

Docs: https://www.toontownrewritten.com/api/localapi
"""

import http.client
import json
import re
import secrets
import subprocess
import threading

TTR_API_PORT_START = 1547
TTR_API_PORT_END   = 1552
TTR_API_HOSTS      = ["::1", "127.0.0.1"]  # TTR prefers IPv6, fall back to IPv4
TTR_USER_AGENT     = "ToonTown MultiTool"

# Single random token for the lifetime of the app session.
# TTR will prompt the user to approve once per instance per session.
_AUTH_TOKEN = secrets.token_hex(16)


def _fetch_toon(port: int, timeout: float = 5.0) -> dict | None:
    """Query /toon.json on the given port. Tries IPv6 then IPv4."""
    for host in TTR_API_HOSTS:
        conn_host = f"[{host}]" if ":" in host else host
        try:
            conn = http.client.HTTPConnection(conn_host, port, timeout=timeout)
            conn.request(
                "GET",
                "/toon.json",
                headers={
                    "Host":          f"localhost:{port}",
                    "Authorization": _AUTH_TOKEN,
                    "User-Agent":    TTR_USER_AGENT,
                }
            )
            resp = conn.getresponse()
            if resp.status == 200:
                return json.loads(resp.read().decode())
        except ConnectionRefusedError:
            continue
        except Exception:
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return None


# Cache for port → X position mapping.
# Recomputed only when the set of active window IDs changes.
_cached_port_to_x: dict = {}
_cached_window_ids_fingerprint: frozenset = frozenset()


def _get_port_to_x_position(current_window_ids: list = None) -> dict:
    """
    Build a mapping of API port -> window X position by chaining:
      ss (port -> host PID) ->
      /proc/<pid>/status NSpid (host PID -> namespace PID) ->
      xdotool getwindowpid (window ID -> namespace PID) ->
      xdotool getwindowgeometry (window ID -> X position)

    Returns cached result if window IDs haven't changed since last call.
    """
    global _cached_port_to_x, _cached_window_ids_fingerprint

    fingerprint = frozenset(current_window_ids) if current_window_ids else frozenset()
    if fingerprint == _cached_window_ids_fingerprint and _cached_port_to_x:
        return _cached_port_to_x
    # Step 1: port -> host PID via ss
    port_to_host_pid = {}
    try:
        out = subprocess.check_output(
            ["ss", "-tlnp"], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            m = re.search(r":(\d+)\s+.*TTREngine.*pid=(\d+)", line)
            if m:
                port = int(m.group(1))
                pid  = int(m.group(2))
                if TTR_API_PORT_START <= port <= TTR_API_PORT_END:
                    port_to_host_pid[port] = pid
    except Exception:
        return {}

    # Step 2: host PID -> namespace PID via /proc/<pid>/status NSpid
    host_to_ns_pid = {}
    for host_pid in port_to_host_pid.values():
        try:
            with open(f"/proc/{host_pid}/status") as f:
                for line in f:
                    if line.startswith("NSpid:"):
                        pids = line.split()[1:]
                        if len(pids) >= 2:
                            host_to_ns_pid[host_pid] = int(pids[1])
                        elif len(pids) == 1:
                            host_to_ns_pid[host_pid] = int(pids[0])
                        break
        except Exception:
            pass

    # Step 3: window ID -> namespace PID via xdotool
    win_to_ns_pid = {}
    try:
        wids = subprocess.check_output(
            ["xdotool", "search", "--class", "Toontown Rewritten"],
            stderr=subprocess.DEVNULL
        ).decode().strip().split()
        for wid in wids:
            try:
                pid = int(subprocess.check_output(
                    ["xdotool", "getwindowpid", wid],
                    stderr=subprocess.DEVNULL
                ).decode().strip())
                win_to_ns_pid[wid] = pid
            except Exception:
                pass
    except Exception:
        return {}

    # Step 4: window ID -> X position
    win_to_x = {}
    for wid in win_to_ns_pid:
        try:
            geo = subprocess.check_output(
                ["xdotool", "getwindowgeometry", wid],
                stderr=subprocess.DEVNULL
            ).decode()
            m = re.search(r"Position:\s*(\d+),(\d+)", geo)
            if m:
                win_to_x[wid] = int(m.group(1))
        except Exception:
            pass

    # Step 5: chain port -> host PID -> ns PID -> window ID -> X position
    ns_pid_to_wid = {v: k for k, v in win_to_ns_pid.items()}
    port_to_x = {}
    for port, host_pid in port_to_host_pid.items():
        ns_pid = host_to_ns_pid.get(host_pid)
        if ns_pid is None:
            continue
        wid = ns_pid_to_wid.get(ns_pid)
        if wid is None:
            continue
        x = win_to_x.get(wid)
        if x is not None:
            port_to_x[port] = x

    _cached_port_to_x = port_to_x
    _cached_window_ids_fingerprint = fingerprint
    return port_to_x


# Ports that have already been approved by the user this session.
# These can use a short timeout since no dialog will appear.
_approved_ports: set[int] = set()


def get_toon_names_by_slot(num_slots: int, current_window_ids: list = None) -> list:
    """
    Scan all TTR API ports in parallel, then sort results by window X position
    (left to right) to match the slot assignment order used by input_service.
    Falls back to port order if window position mapping fails.

    Pass current_window_ids to enable caching of the port-to-X map — it is
    only recomputed when the window ID list changes.
    """
    found = {}  # port -> name

    def _query(port):
        timeout = 0.5 if port in _approved_ports else 5.0
        data = _fetch_toon(port, timeout=timeout)
        if data and "name" in data:
            _approved_ports.add(port)
            found[port] = data["name"]

    threads = [
        threading.Thread(target=_query, args=(port,), daemon=True)
        for port in range(TTR_API_PORT_START, TTR_API_PORT_END + 1)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6.0)

    if not found:
        return [None] * num_slots

    # Try to sort by window X position for accurate slot matching
    port_to_x = _get_port_to_x_position(current_window_ids)
    if port_to_x:
        ordered = sorted(
            [(port, name) for port, name in found.items() if port in port_to_x],
            key=lambda item: port_to_x[item[0]]
        )
        # Append any ports we couldn't map, sorted by port as fallback
        mapped_ports = {p for p, _ in ordered}
        for port, name in sorted(found.items()):
            if port not in mapped_ports:
                ordered.append((port, name))
    else:
        # Fallback: sort by port number (launch order)
        ordered = sorted(found.items())

    names = [None] * num_slots
    for i, (port, name) in enumerate(ordered):
        if i < num_slots:
            names[i] = name

    return names


def get_toon_names_threaded(num_slots: int, callback, current_window_ids: list = None) -> None:
    """
    Fetch toon names in a background thread and call callback(names) on
    completion. callback receives a list of length num_slots.
    """
    def _run():
        names = get_toon_names_by_slot(num_slots, current_window_ids)
        callback(names)

    t = threading.Thread(target=_run, daemon=True)
    t.start()