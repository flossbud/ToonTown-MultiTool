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
_AUTH_TOKEN        = secrets.token_hex(16)

_DEBUG = False
_log_callback = None
_last_logged = {}  # port -> log string (only log when values change)
_last_debug_logged = {}  # key -> log string (only log when values change)
_last_logged_lock = threading.Lock()
_last_debug_logged_lock = threading.Lock()


def set_debug(enabled: bool) -> None:
    """Enable or disable verbose toon-data logging (routed through the debug tab)."""
    global _DEBUG
    _DEBUG = enabled


def set_log_callback(callback) -> None:
    """Set a callback for API log messages (goes to debug tab, not terminal)."""
    global _log_callback
    _log_callback = callback


def _debug_log(key: str, msg: str) -> None:
    """Emit debug log lines only when content changes."""
    if not (_DEBUG and _log_callback):
        return
    with _last_debug_logged_lock:
        if _last_debug_logged.get(key) == msg:
            return
        _last_debug_logged[key] = msg
    _log_callback(msg)


def _fetch_toon(port: int, timeout: float = 5.0) -> dict | None:
    """Query /all.json on the given port to get toon, laff, and bean data. Tries IPv6 then IPv4."""
    for host in TTR_API_HOSTS:
        conn_host = f"[{host}]" if ":" in host else host
        try:
            conn = http.client.HTTPConnection(conn_host, port, timeout=timeout)
            conn.request(
                "GET", "/all.json",
                headers={
                    "Host":          f"localhost:{port}",
                    "Authorization": _AUTH_TOKEN,
                    "User-Agent":    TTR_USER_AGENT,
                }
            )
            resp = conn.getresponse()
            if resp.status == 200:
                return json.loads(resp.read().decode())
        except (OSError, ValueError, KeyError) as e:
            _debug_log(f"fetch_failed_{host}_{port}", f"[TTR API] Fetch failed on port {port}: {e}")
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return None


# ── port → window_id cache ────────────────────────────────────────────────────
_port_to_wid: dict = {}
_port_to_wid_fingerprint = None
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
                stderr=subprocess.DEVNULL,
                timeout=1.0
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


def _build_port_to_window_id(current_window_ids: list, active_ports: set | None = None) -> dict:
    """
    Build and cache a stable mapping of API port -> window ID.
    Only recomputes if current_window_ids has changed since last call.
    """
    global _port_to_wid, _port_to_wid_fingerprint

    windows_fp = frozenset(current_window_ids) if current_window_ids else frozenset()
    active_ports_fp = frozenset(active_ports) if active_ports else frozenset()
    with _approved_ports_lock:
        approved_ports_fp = frozenset(_approved_ports)
    fingerprint = (windows_fp, active_ports_fp, approved_ports_fp)

    with _port_to_wid_lock:
        if fingerprint == _port_to_wid_fingerprint and _port_to_wid:
            return dict(_port_to_wid)

        port_to_host_pid = {}
        try:
            import sys
            if sys.platform == "win32":
                # CREATE_NO_WINDOW prevents a console flash when the parent .exe
                # is built windowed (PyInstaller console=False).
                out = subprocess.check_output(
                    ["netstat", "-ano"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                ).decode()
                for line in out.splitlines():
                    if "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                port_str = parts[1].split(":")[-1]
                                pid = int(parts[-1])
                                port = int(port_str)
                                if TTR_API_PORT_START <= port <= TTR_API_PORT_END:
                                    port_to_host_pid[port] = pid
                            except ValueError:
                                continue
            else:
                from utils.host_spawn import host_check_output
                out = host_check_output(["ss", "-tlnp"], stderr=subprocess.DEVNULL, timeout=5).decode()
                for line in out.splitlines():
                    m = re.search(r":(\d+)\s+.*TTREngine.*pid=(\d+)", line)
                    if m:
                        port = int(m.group(1))
                        pid  = int(m.group(2))
                        if TTR_API_PORT_START <= port <= TTR_API_PORT_END:
                            port_to_host_pid[port] = pid
        except subprocess.TimeoutExpired:
            _debug_log("port_pid_timeout", "[TTR API] Port->PID probe timed out; skipping this cycle.")
            return {}
        except Exception:
            return {}

        _debug_log(
            "port_to_host_pid",
            f"[TTR API] Port->Host PID candidates: {dict(sorted(port_to_host_pid.items()))}"
        )

        import sys
        if sys.platform == "win32":
            wid_to_host_pid = {}
            try:
                import win32process
                for wid_str in (current_window_ids or []):
                    try:
                        hwnd = int(wid_str)
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        wid_to_host_pid[wid_str] = pid
                    except Exception:
                        continue
            except Exception:
                pass
        else:
            wid_to_host_pid = _get_window_pids_xres(current_window_ids)
            if not wid_to_host_pid:
                wid_to_host_pid = _get_window_pids_nspid(
                    current_window_ids, set(port_to_host_pid.values())
                )

        _debug_log(
            "wid_to_host_pid",
            f"[TTR API] Window->Host PID candidates: {dict(sorted(wid_to_host_pid.items()))}"
        )

        # Multiple top-level HWNDs can exist per process on Windows.
        # Keep all windows per PID and assign ports in stable order.
        host_pid_to_wids = {}
        for wid in (current_window_ids or []):
            pid = wid_to_host_pid.get(wid)
            if pid is None:
                continue
            host_pid_to_wids.setdefault(pid, []).append(wid)

        _debug_log(
            "host_pid_to_wids",
            f"[TTR API] Host PID->Window list: {dict(sorted(host_pid_to_wids.items()))}"
        )

        result = {}
        host_pid_to_next_idx = {}
        for port in sorted(port_to_host_pid):
            host_pid = port_to_host_pid[port]
            wids = host_pid_to_wids.get(host_pid, [])
            idx = host_pid_to_next_idx.get(host_pid, 0)
            if idx < len(wids):
                result[port] = wids[idx]
                host_pid_to_next_idx[host_pid] = idx + 1

        _debug_log(
            "port_to_wid_result",
            f"[TTR API] Final Port->Window mapping: {dict(sorted(result.items()))}"
        )

        _port_to_wid = result
        _port_to_wid_fingerprint = fingerprint
        return dict(result)


def invalidate_port_to_wid_cache():
    """Force port->window_id to be rebuilt on next fetch."""
    global _port_to_wid, _port_to_wid_fingerprint
    with _port_to_wid_lock:
        _port_to_wid = {}
        _port_to_wid_fingerprint = None
    with _last_debug_logged_lock:
        _last_debug_logged.clear()


# ── window_id → name + style + color cache ────────────────────────────────────
_wid_to_name: dict = {}
_wid_to_style: dict = {}   # window_id -> Rendition DNA string
_wid_to_color: dict = {}   # window_id -> headColor hex string
_wid_to_laff: dict = {}
_wid_to_max_laff: dict = {}
_wid_to_beans: dict = {}
_wid_to_timestamp: dict = {}
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
            _wid_to_laff.pop(wid, None)
            _wid_to_max_laff.pop(wid, None)
            _wid_to_beans.pop(wid, None)
            _wid_to_timestamp.pop(wid, None)


# ── Smart port scanning state (fix #7) ────────────────────────────────────────
_approved_ports: set = set()
_approved_ports_lock = threading.Lock()
_last_full_scan_time: float = 0.0
_last_full_scan_wids: frozenset = frozenset()
_full_scan_state_lock = threading.Lock()
_FULL_SCAN_COOLDOWN = 30.0


def _should_full_scan(current_window_ids: list) -> bool:
    global _last_full_scan_time, _last_full_scan_wids
    now = time.monotonic()
    current_fp = frozenset(current_window_ids) if current_window_ids else frozenset()
    with _approved_ports_lock:
        approved_ports_snapshot = set(_approved_ports)
    with _full_scan_state_lock:
        last_scan_time = _last_full_scan_time
        last_scan_wids = _last_full_scan_wids
    if not approved_ports_snapshot:
        return True
    if current_fp != last_scan_wids:
        return True
    if now - last_scan_time >= _FULL_SCAN_COOLDOWN:
        return True
    return False


def _mark_full_scan_done(current_window_ids: list):
    global _last_full_scan_time, _last_full_scan_wids
    with _full_scan_state_lock:
        _last_full_scan_time = time.monotonic()
        _last_full_scan_wids = frozenset(current_window_ids) if current_window_ids else frozenset()


# ── Public API ────────────────────────────────────────────────────────────────

def get_toon_names_by_slot(num_slots: int, current_window_ids: list = None):
    """
    Fetch toon names, styles, and head colors ordered by slot.
    Returns (names, styles, colors) — all lists of length num_slots.
    """
    found = {}  # port -> (name, style, headColor)
    found_lock = threading.Lock()

    def _query(port):
        with _approved_ports_lock:
            already_approved = port in _approved_ports
        timeout = 0.5 if already_approved else 5.0
        data = _fetch_toon(port, timeout=timeout)
        if data and "toon" in data and "name" in data["toon"]:
            with _approved_ports_lock:
                _approved_ports.add(port)
            toon_data = data["toon"]
            name = toon_data["name"]
            style = toon_data.get("style")
            headColor = toon_data.get("headColor")

            laff_data = data.get("laff", {})
            current_laff = laff_data.get("current")
            max_laff = laff_data.get("max")

            beans_data = data.get("beans", {}).get("bank", {})
            bank_beans = beans_data.get("current")

            if _DEBUG and _log_callback:
                msg = f"[TTR API] Port {port}: name={name!r}, laff={current_laff}/{max_laff}, bank={bank_beans}"
                with _last_logged_lock:
                    if _last_logged.get(port) != msg:
                        _last_logged[port] = msg
                        _log_callback(msg)
            with found_lock:
                found[port] = (name, style, headColor, current_laff, max_laff, bank_beans)

    do_full_scan = _should_full_scan(current_window_ids)
    with _approved_ports_lock:
        ports_to_scan = (
            list(range(TTR_API_PORT_START, TTR_API_PORT_END + 1))
            if do_full_scan else list(_approved_ports)
        )

    if not ports_to_scan:
        return [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots

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
        with _approved_ports_lock:
            _approved_ports.intersection_update(found.keys())
        # Clean stale log cache entries
        with _last_logged_lock:
            for p in list(_last_logged):
                if p not in found:
                    _last_logged.pop(p, None)

    if not found:
        return [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots, [None]*num_slots

    found_names  = {p: v[0] for p, v in found.items()}
    found_styles = {p: v[1] for p, v in found.items()}
    found_colors = {p: v[2] for p, v in found.items()}
    found_laff   = {p: v[3] for p, v in found.items()}
    found_max_laff = {p: v[4] for p, v in found.items()}
    found_beans  = {p: v[5] for p, v in found.items()}

    port_to_wid = _build_port_to_window_id(current_window_ids or [], set(found_names.keys()))

    expected_mappings = min(len(found_names), len(current_window_ids or []))
    if current_window_ids and found_names and len(port_to_wid) < expected_mappings:
        mapped_ports = set(port_to_wid)
        mapped_wids = set(port_to_wid.values())
        remaining_ports = [p for p in sorted(found_names.keys()) if p not in mapped_ports]
        remaining_wids = [wid for wid in current_window_ids if wid not in mapped_wids]
        for port, wid in zip(remaining_ports, remaining_wids):
            port_to_wid[port] = wid

        _debug_log(
            "port_to_wid_fallback",
            f"[TTR API] Applied partial fallback mapping: {dict(sorted(port_to_wid.items()))}"
        )

    with _wid_to_name_lock:
        active_wids_with_data = set()
        for port, name in found_names.items():
            wid = port_to_wid.get(port)
            if wid:
                active_wids_with_data.add(wid)
                _wid_to_name[wid] = name
                _wid_to_timestamp[wid] = time.monotonic()
                style = found_styles.get(port)
                if style:
                    _wid_to_style[wid] = style
                color = found_colors.get(port)
                if color:
                    _wid_to_color[wid] = color
                laff = found_laff.get(port)
                if laff is not None:
                    _wid_to_laff[wid] = laff
                max_laff = found_max_laff.get(port)
                if max_laff is not None:
                    _wid_to_max_laff[wid] = max_laff
                beans = found_beans.get(port)
                if beans is not None:
                    _wid_to_beans[wid] = beans

        # Clear out any windows that are open but no longer returned API data (e.g. logged out back to menu)
        for wid in current_window_ids or []:
            if wid not in active_wids_with_data:
                _wid_to_name.pop(wid, None)
                _wid_to_style.pop(wid, None)
                _wid_to_color.pop(wid, None)
                _wid_to_laff.pop(wid, None)
                _wid_to_max_laff.pop(wid, None)
                _wid_to_beans.pop(wid, None)
                _wid_to_timestamp.pop(wid, None)

        name_snapshot  = dict(_wid_to_name)
        style_snapshot = dict(_wid_to_style)
        color_snapshot = dict(_wid_to_color)
        laff_snapshot  = dict(_wid_to_laff)
        max_laff_snapshot = dict(_wid_to_max_laff)
        beans_snapshot = dict(_wid_to_beans)

    names  = [None] * num_slots
    styles = [None] * num_slots
    colors = [None] * num_slots
    laffs  = [None] * num_slots
    max_laffs = [None] * num_slots
    beans  = [None] * num_slots

    if current_window_ids is not None:
        for i, wid in enumerate(current_window_ids):
            if i < num_slots:
                names[i]  = name_snapshot.get(wid)
                styles[i] = style_snapshot.get(wid)
                colors[i] = color_snapshot.get(wid)
                laffs[i]  = laff_snapshot.get(wid)
                max_laffs[i] = max_laff_snapshot.get(wid)
                beans[i]  = beans_snapshot.get(wid)
    else:
        for i, (port, name) in enumerate(sorted(found_names.items())):
            if i < num_slots:
                names[i]  = name
                styles[i] = found_styles.get(port)
                colors[i] = found_colors.get(port)
                laffs[i]  = found_laff.get(port)
                max_laffs[i] = found_max_laff.get(port)
                beans[i]  = found_beans.get(port)

    return names, styles, colors, laffs, max_laffs, beans


def get_toon_names_threaded(num_slots: int, callback, current_window_ids: list = None) -> None:
    """
    Fetch toon names, styles, head colors, laff, max_laff, and beans down in a background thread.
    callback(names, styles, colors, laffs, max_laffs, beans) is called on completion.
    """
    def _run():
        res = get_toon_names_by_slot(num_slots, current_window_ids)
        callback(*res)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
