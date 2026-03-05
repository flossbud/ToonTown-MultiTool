"""
TTR Local (Companion App) API client.

Architecture:
  - port -> window_id  : built once per session, only recomputed if windows open/close
  - window_id -> name  : refreshed every fetch cycle (handles logout/re-login)
  - slot i -> window_ids[i] -> name : slot order comes from input_service (already left-to-right)

Fix #7: Smart port scanning
  - Known-good ports (previously responded) are queried every 5s cycle
  - Full port range scan only triggers when new windows are detected or
    every 30 seconds, avoiding 6 thread spawns on every refresh

Docs: https://www.toontownrewritten.com/api/localapi
"""

import http.client
import json
import re
import secrets
import subprocess
import threading
import time

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
_port_to_wid: dict = {}
_port_to_wid_fingerprint: frozenset = frozenset()
_port_to_wid_lock = threading.Lock()


def _get_window_pids_xres(window_ids: list) -> dict:
    """Use XRes extension to get host PIDs for windows.

    The X server always sees the real host PID of each client, even when the
    client runs inside a Flatpak/container namespace. This bypasses the broken
    NSpid mapping that gives every Flatpak instance the same namespace PID.

    Returns {wid_str: host_pid} or {} if XRes is unavailable.
    """
    if not window_ids:
        return {}
    try:
        from Xlib import display as xdisplay
        from Xlib.ext import res as xres
        d = xdisplay.Display()
        try:
            if not d.has_extension("X-Resource"):
                return {}
            result = {}
            for wid_str in window_ids:
                try:
                    wid = int(wid_str)
                    resp = d.res_query_client_ids(
                        [{"client": wid, "mask": xres.LocalClientPIDMask}]
                    )
                    for cid in resp.ids:
                        if cid.value:
                            result[wid_str] = cid.value[0]
                            break
                except Exception:
                    continue
            return result
        finally:
            d.close()
    except Exception:
        return {}


def _get_window_pids_nspid(window_ids: list, host_pids: set) -> dict:
    """Fallback: map window IDs to host PIDs via NSpid + xdotool."""
    host_to_ns_pid = {}
    for host_pid in host_pids:
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

    win_to_ns_pid = {}
    for wid in (window_ids or []):
        try:
            pid = int(subprocess.check_output(
                ["xdotool", "getwindowpid", wid],
                stderr=subprocess.DEVNULL
            ).decode().strip())
            win_to_ns_pid[wid] = pid
        except Exception:
            pass

    ns_pid_to_host = {ns: host for host, ns in host_to_ns_pid.items()}

    result = {}
    for wid, ns_pid in win_to_ns_pid.items():
        host_pid = ns_pid_to_host.get(ns_pid)
        if host_pid is not None:
            result[wid] = host_pid
    return result


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

        wid_to_host_pid = _get_window_pids_xres(current_window_ids)
        if not wid_to_host_pid:
            wid_to_host_pid = _get_window_pids_nspid(
                current_window_ids, set(port_to_host_pid.values())
            )

        host_pid_to_wid = {pid: wid for wid, pid in wid_to_host_pid.items()}
        result = {}
        for port, host_pid in port_to_host_pid.items():
            wid = host_pid_to_wid.get(host_pid)
            if wid is not None:
                result[port] = wid

        _port_to_wid = result
        _port_to_wid_fingerprint = fingerprint
        return dict(result)


def invalidate_port_to_wid_cache():
    """Force port->window_id to be rebuilt on next fetch."""
    global _port_to_wid, _port_to_wid_fingerprint
    with _port_to_wid_lock:
        _port_to_wid = {}
        _port_to_wid_fingerprint = frozenset()


# ── window_id → name + style + color cache ────────────────────────────────────
_wid_to_name: dict = {}
_wid_to_style: dict = {}   # window_id -> Rendition DNA string
_wid_to_color: dict = {}   # window_id -> headColor hex string
_wid_to_name_lock = threading.Lock()


def clear_stale_names(current_window_ids: list):
    """Remove cached names for windows that no longer exist."""
    valid = set(current_window_ids) if current_window_ids else set()
    with _wid_to_name_lock:
        stale = [wid for wid in _wid_to_name if wid not in valid]
        for wid in stale:
            del _wid_to_name[wid]
            _wid_to_style.pop(wid, None)
            _wid_to_color.pop(wid, None)


# ── Smart port scanning state (fix #7) ────────────────────────────────────────
_approved_ports: set = set()
_last_full_scan_time: float = 0.0
_last_full_scan_wids: frozenset = frozenset()
_FULL_SCAN_COOLDOWN = 30.0


def _should_full_scan(current_window_ids: list) -> bool:
    global _last_full_scan_time, _last_full_scan_wids
    now = time.monotonic()
    current_fp = frozenset(current_window_ids) if current_window_ids else frozenset()
    if not _approved_ports:
        return True
    if current_fp != _last_full_scan_wids:
        return True
    if now - _last_full_scan_time >= _FULL_SCAN_COOLDOWN:
        return True
    return False


def _mark_full_scan_done(current_window_ids: list):
    global _last_full_scan_time, _last_full_scan_wids
    _last_full_scan_time = time.monotonic()
    _last_full_scan_wids = frozenset(current_window_ids) if current_window_ids else frozenset()


# ── Public API ────────────────────────────────────────────────────────────────

def get_toon_names_by_slot(num_slots: int, current_window_ids: list = None):
    """
    Fetch toon names, styles, and head colors ordered by slot.
    Returns (names, styles, colors) — all lists of length num_slots.
    """
    found = {}  # port -> (name, style, headColor)

    def _query(port):
        timeout = 0.5 if port in _approved_ports else 5.0
        data = _fetch_toon(port, timeout=timeout)
        if data and "name" in data:
            _approved_ports.add(port)
            style = data.get("style")
            print(f"[TTR API] Port {port}: name={data['name']!r}, style={style!r}")
            found[port] = (data["name"], style, data.get("headColor"))

    do_full_scan = _should_full_scan(current_window_ids)
    ports_to_scan = (
        list(range(TTR_API_PORT_START, TTR_API_PORT_END + 1))
        if do_full_scan else list(_approved_ports)
    )

    if not ports_to_scan:
        return [None] * num_slots, [None] * num_slots, [None] * num_slots

    threads = [
        threading.Thread(target=_query, args=(port,), daemon=True)
        for port in ports_to_scan
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6.0)

    if do_full_scan:
        _mark_full_scan_done(current_window_ids)
        # Prune ports that didn't respond (toon closed/logged out)
        _approved_ports.intersection_update(found.keys())

    if not found:
        return [None] * num_slots, [None] * num_slots, [None] * num_slots

    found_names  = {p: v[0] for p, v in found.items()}
    found_styles = {p: v[1] for p, v in found.items()}
    found_colors = {p: v[2] for p, v in found.items()}

    port_to_wid = _build_port_to_window_id(current_window_ids or [])

    wids_mapped = set(port_to_wid.values())
    mapping_ok = (
        current_window_ids and
        len(wids_mapped) == len(found_names) and
        len(wids_mapped) == len(current_window_ids)
    )
    if not mapping_ok and current_window_ids:
        sorted_ports = sorted(found_names.keys())
        port_to_wid = {
            port: current_window_ids[i]
            for i, port in enumerate(sorted_ports)
            if i < len(current_window_ids)
        }

    with _wid_to_name_lock:
        for port, name in found_names.items():
            wid = port_to_wid.get(port)
            if wid:
                _wid_to_name[wid] = name
                style = found_styles.get(port)
                if style:
                    _wid_to_style[wid] = style
                color = found_colors.get(port)
                if color:
                    _wid_to_color[wid] = color
        name_snapshot  = dict(_wid_to_name)
        style_snapshot = dict(_wid_to_style)
        color_snapshot = dict(_wid_to_color)

    names  = [None] * num_slots
    styles = [None] * num_slots
    colors = [None] * num_slots
    if current_window_ids:
        for i, wid in enumerate(current_window_ids):
            if i < num_slots:
                names[i]  = name_snapshot.get(wid)
                styles[i] = style_snapshot.get(wid)
                colors[i] = color_snapshot.get(wid)
    else:
        for i, (port, name) in enumerate(sorted(found_names.items())):
            if i < num_slots:
                names[i]  = name
                styles[i] = found_styles.get(port)
                colors[i] = found_colors.get(port)

    return names, styles, colors


def get_toon_names_threaded(num_slots: int, callback, current_window_ids: list = None) -> None:
    """
    Fetch toon names, styles, and head colors in a background thread.
    callback(names, styles, colors) is called on completion.
    """
    def _run():
        names, styles, colors = get_toon_names_by_slot(num_slots, current_window_ids)
        callback(names, styles, colors)

    t = threading.Thread(target=_run, daemon=True)
    t.start()