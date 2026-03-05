import subprocess
import threading
import time
from PySide6.QtCore import QObject, Signal

class WindowManager(QObject):
    window_ids_updated = Signal(list)
    active_window_changed = Signal(str)

    POLL_INTERVAL = 0.1

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager
        
        self.ttr_window_ids = []
        self._active_id = None
        
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        
        self.multitool_id = None

    def start(self):
        if self.settings_manager:
            self.multitool_id = str(self.settings_manager.get("multitool_window_id", ""))
        self._running = True
        self.assign_windows()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        last_active = None
        last_assign_time = 0
        
        while self._running:
            # Poll active window
            try:
                result = subprocess.check_output(
                    ["xdotool", "getactivewindow"],
                    stderr=subprocess.DEVNULL
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
        try:
            raw_ids = subprocess.check_output(
                ["xdotool", "search", "--class", "Toontown Rewritten"],
                stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")

            visible = []
            for wid in (w.strip() for w in raw_ids if w.strip()):
                try:
                    geo = subprocess.check_output(
                        ["xdotool", "getwindowgeometry", wid],
                        stderr=subprocess.DEVNULL
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
            new_ids = list(dict.fromkeys(w for w, _ in visible))[:4]
        except subprocess.CalledProcessError:
            new_ids = []

        if new_ids != self.ttr_window_ids:
            self.ttr_window_ids = new_ids
            self.window_ids_updated.emit(self.ttr_window_ids)

    def is_multitool_active(self) -> bool:
        active = self.get_active_window()
        return bool(active and self.multitool_id and active == self.multitool_id)
        
    def is_ttr_active(self) -> bool:
        active = self.get_active_window()
        return bool(active and active in self.ttr_window_ids)

    def should_capture_input(self) -> bool:
        """Only capture global hotkeys if TTR or the MultiTool itself is focused."""
        return self.is_ttr_active() or self.is_multitool_active()
