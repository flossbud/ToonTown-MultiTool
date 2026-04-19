import subprocess
import threading
import time
from PySide6.QtCore import QObject, Signal
from utils.game_registry import GameRegistry

class WindowManager(QObject):
    window_ids_updated = Signal(list)
    active_window_changed = Signal(str)

    POLL_INTERVAL = 0.1

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager

        self.ttr_window_ids = []
        self._active_id = None
        self._detection_enabled = False

        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        
        self.multitool_id = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        if self.settings_manager:
            self.multitool_id = str(self.settings_manager.get("multitool_window_id", ""))
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def enable_detection(self):
        self._detection_enabled = True
        self.assign_windows()

    def disable_detection(self):
        self._detection_enabled = False
        with self._lock:
            self._active_id = None
            had_ids = bool(self.ttr_window_ids)
            self.ttr_window_ids = []
            snapshot = list(self.ttr_window_ids)
        if had_ids:
            self.window_ids_updated.emit(snapshot)

    def stop(self):
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def get_window_ids(self) -> list:
        with self._lock:
            return list(self.ttr_window_ids)

    def clear_window_ids(self):
        with self._lock:
            self.ttr_window_ids = []
            snapshot = list(self.ttr_window_ids)
        self.window_ids_updated.emit(snapshot)

    @property
    def active_window_id(self):
        with self._lock:
            return self._active_id

    def _poll_loop(self):
        last_active = None
        last_assign_time = 0
        
        while self._running:
            if not self._detection_enabled:
                time.sleep(self.POLL_INTERVAL)
                continue

            # Poll active window
            import sys
            if sys.platform == "win32":
                try:
                    import win32gui
                    hwnd = win32gui.GetForegroundWindow()
                    current_active = str(hwnd) if hwnd else None
                except Exception:
                    current_active = None
            else:
                try:
                    result = subprocess.check_output(
                        ["xdotool", "getactivewindow"],
                        stderr=subprocess.DEVNULL,
                        timeout=0.5
                    ).decode().strip()
                    current_active = result
                except Exception:
                    current_active = None
                
            with self._lock:
                self._active_id = current_active
                
            if current_active != last_active:
                self.active_window_changed.emit(current_active or "")
                last_active = current_active

            # Periodically re-assign windows (e.g. every 2 seconds) just in case
            now = time.monotonic()
            if now - last_assign_time > 2.0:
                self.assign_windows()
                last_assign_time = now

            time.sleep(self.POLL_INTERVAL)

    def get_active_window(self):
        with self._lock:
            return self._active_id

    def assign_windows(self):
        """Detect TTR windows and sort left-to-right."""
        if not self._detection_enabled:
            return

        registry = GameRegistry.instance()

        def _accept_candidate_window(wid: str) -> bool:
            game, confirmed = registry.classify_window_for_filtering(wid)
            return not confirmed or game is not None

        import sys
        if sys.platform == "win32":
            try:
                import win32gui
                import win32con
                visible = []

                def _is_candidate_toon_window(hwnd, title: str) -> bool:
                    if not title:
                        return False
                    if "Toontown Rewritten" not in title and "Corporate Clash" not in title:
                        return False
                    # Exclude non-primary/utility windows that can appear for the same process.
                    if win32gui.GetParent(hwnd):
                        return False
                    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                        return False
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                    if style & win32con.WS_CHILD:
                        return False
                    if ex_style & win32con.WS_EX_TOOLWINDOW:
                        return False
                    try:
                        l, t, r, b = win32gui.GetClientRect(hwnd)
                        w = max(0, r - l)
                        h = max(0, b - t)
                        if w < 300 or h < 200:
                            return False
                    except Exception:
                        return False
                    return True

                def enum_windows_proc(hwnd, lParam):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if _is_candidate_toon_window(hwnd, title):
                            wid = str(hwnd)
                            if not _accept_candidate_window(wid):
                                return
                            pt = win32gui.ClientToScreen(hwnd, (0, 0))
                            x = pt[0]
                            visible.append((wid, x))
                win32gui.EnumWindows(enum_windows_proc, 0)
                visible.sort(key=lambda item: (item[1], item[0]))
                new_ids = list(dict.fromkeys(w for w, _ in visible))[:16]
            except Exception:
                new_ids = []
        else:
            try:
                raw_ids = []
                for cls in ("Toontown Rewritten", "Corporate Clash"):
                    try:
                        out = subprocess.check_output(
                            ["xdotool", "search", "--class", cls],
                            stderr=subprocess.DEVNULL,
                            timeout=0.5
                        ).decode().strip().split("\n")
                        raw_ids.extend([w.strip() for w in out if w.strip() and w.strip().isdigit()])
                    except subprocess.CalledProcessError:
                        pass

                visible = []
                for wid in raw_ids:
                    if not _accept_candidate_window(wid):
                        continue
                    try:
                        geo = subprocess.check_output(
                            ["xdotool", "getwindowgeometry", wid],
                            stderr=subprocess.DEVNULL,
                            timeout=0.5
                        ).decode()
                        if "Position:" in geo and "Geometry:" in geo:
                            x = 99999
                            for line in geo.splitlines():
                                if "Position:" in line:
                                    x = int(line.split()[1].split(",")[0])
                                    break
                            visible.append((wid, x))
                    except subprocess.CalledProcessError:
                        continue

                visible.sort(key=lambda item: (item[1], item[0]))
                new_ids = list(dict.fromkeys(w for w, _ in visible))[:16]
            except Exception:
                new_ids = []

        with self._lock:
            changed = new_ids != self.ttr_window_ids
            if changed:
                self.ttr_window_ids = list(new_ids)
            snapshot = list(self.ttr_window_ids)
        if changed:
            self.window_ids_updated.emit(snapshot)

    def is_multitool_active(self) -> bool:
        active = self.active_window_id
        return bool(active and self.multitool_id and active == self.multitool_id)
        
    def is_ttr_active(self) -> bool:
        active = self.active_window_id
        with self._lock:
            return bool(active and active in self.ttr_window_ids)

    def should_capture_input(self) -> bool:
        """Only capture global hotkeys if TTR or the MultiTool itself is focused."""
        return self.is_ttr_active() or self.is_multitool_active()
