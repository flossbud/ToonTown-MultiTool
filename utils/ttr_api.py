"""
TTR Local (Companion App) API client.

Architecture:
  - port -> window_id  : built once per session, only recomputed if windows open/close
  - window_id -> name  : refreshed every fetch cycle (handles logout/re-login)
  - slot i -> window_ids[i] -> name : slot order comes from input_service (already left-to-right)

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

_AUTH_TOKEN = secrets.token_hex(16)


def _fetch_toon(port: int, timeout: float = 5.0) -> dict | None:
    """Query /toon.json on the given port. Tries IPv6 then IPv4."""
    for host in TTR_API_HOSTS:
        conn_host = f"[{host}]" if ":" in host else host
        try:
            conn = http.client.HTTPConnection(conn_host, port, timeout=timeout)
            conn.request(
                "GET", "/toon.json",
                headers={
                    "Host":          f"localhost:{port}",
                    "Authorization": _AUTH_TOKEN,
                    "User-Agent":    TTR_USER_AGENT,
                }
            )
            resp = conn.getresponse()
            if resp.status == 200:
                return json.loads(resp.read().decode())
        except Exception:
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return None


# ── port → window_id cache ────────────────────────────────────────────────────
# Built by chaining: ss (port→pid) → /proc NSpid (pid→ns_pid) → xdotool (ns_pid→window_id)
# Recomputed only when the set of active window IDs changes.
_port_to_wid: dict = {}
_port_to_wid_fingerprint: frozenset = frozenset()
_port_to_wid_lock = threading.Lock()


def _build_port_to_window_id(current_window_ids: list) -> dict:
    """
    Build and cache a stable mapping of API port -> window ID.
    Only recomputes if current_window_ids has changed since last call.
    """
    global _port_to_wid, _port_to_wid_fingerprint

    fingerprint = frozenset(current_window_ids) if current_window_ids else frozenset()

    with _port_to_wid_lock:
        if fingerprint == _port_to_wid_fingerprint and _port_to_wid:
            return dict(_port_to_wid)

        # Step 1: port -> host PID via ss
        port_to_host_pid = {}
        try:
            out = subprocess.check_output(["ss", "-tlnp"], stderr=subprocess.DEVNULL).decode()
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
        # Only consider windows already validated by assign_windows
        win_to_ns_pid = {}
        for wid in (current_window_ids or []):
            try:
                pid = int(subprocess.check_output(
                    ["xdotool", "getwindowpid", wid],
                    stderr=subprocess.DEVNULL
                ).decode().strip())
                win_to_ns_pid[wid] = pid
            except Exception:
                pass

        # Step 4: chain port -> host PID -> ns PID -> window ID
        ns_pid_to_wid = {v: k for k, v in win_to_ns_pid.items()}
        result = {}
        for port, host_pid in port_to_host_pid.items():
            ns_pid = host_to_ns_pid.get(host_pid)
            if ns_pid is None:
                continue
            wid = ns_pid_to_wid.get(ns_pid)
            if wid is not None:
                result[port] = wid

        _port_to_wid = result
        _port_to_wid_fingerprint = fingerprint
        return dict(result)


def invalidate_port_to_wid_cache():
    """Force port->window_id to be rebuilt on next fetch.
    Call on manual refresh so window repositioning is picked up."""
    global _port_to_wid, _port_to_wid_fingerprint
    with _port_to_wid_lock:
        _port_to_wid = {}
        _port_to_wid_fingerprint = frozenset()


# ── window_id → name cache ────────────────────────────────────────────────────
# Updated every fetch. Never cleared — window IDs are stable for the app lifetime.
_wid_to_name: dict = {}
_wid_to_name_lock = threading.Lock()

# Ports approved by the user this session — short timeout reused.
_approved_ports: set = set()


# ── Public API ────────────────────────────────────────────────────────────────

def get_toon_names_by_slot(num_slots: int, current_window_ids: list = None) -> list:
    """
    Fetch toon names and return them ordered by slot.

    Slot order is determined entirely by current_window_ids, which input_service
    already sorts left-to-right. No sorting is done here.
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

    # Get the stable port -> window_id mapping
    port_to_wid = _build_port_to_window_id(current_window_ids or [])

    # Detect broken PID mapping — Flatpak gives every instance ns_pid=59,
    # causing all ports to map to the same window ID.
    # Fallback: correlate by launch order.
    #   - TTR assigns ports sequentially: lower port = launched first
    #   - X11 assigns window IDs sequentially: lower wid = created first
    #   Both reflect instance creation order, so sorting both ascending
    #   and matching by index gives the correct port→window mapping.
    wids_mapped = set(port_to_wid.values())
    mapping_ok = (
        current_window_ids and
        len(wids_mapped) == len(found) and
        len(wids_mapped) == len(current_window_ids)
    )
    if not mapping_ok and current_window_ids:
        sorted_ports = sorted(found.keys())
        sorted_wids  = sorted(current_window_ids, key=lambda w: int(w))
        port_to_wid = {
            port: sorted_wids[i]
            for i, port in enumerate(sorted_ports)
            if i < len(sorted_wids)
        }

    # Update window_id -> name cache
    with _wid_to_name_lock:
        for port, name in found.items():
            wid = port_to_wid.get(port)
            if wid:
                _wid_to_name[wid] = name
        name_snapshot = dict(_wid_to_name)

    # Assign names to slots by looking up each slot's window_id.
    # Slot order comes entirely from current_window_ids — no sorting here.
    names = [None] * num_slots
    if current_window_ids:
        for i, wid in enumerate(current_window_ids):
            if i < num_slots:
                names[i] = name_snapshot.get(wid)
    else:
        for i, (_, name) in enumerate(sorted(found.items())):
            if i < num_slots:
                names[i] = name

    return names


def get_toon_names_threaded(num_slots: int, callback, current_window_ids: list = None) -> None:
    """
    Fetch toon names in a background thread and call callback(names) on completion.
    """
    def _run():
        names = get_toon_names_by_slot(num_slots, current_window_ids)
        callback(names)

    t = threading.Thread(target=_run, daemon=True)
    t.start()