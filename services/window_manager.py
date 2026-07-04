# Deferred annotations: the deb/AppImage bundles run Python 3.9, where a
# def-time `tuple[...] | None` annotation raises TypeError without this.
from __future__ import annotations

import sys
import threading
import time
from PySide6.QtCore import QObject, Signal
from utils.game_registry import GameRegistry
from utils import x11_discovery
from utils.window_cell_assignment import assign_window_cells


def _geometry_backend():
    """Platform dispatch for window-geometry queries."""
    if sys.platform == "win32":
        from utils import win32_discovery
        return win32_discovery
    if sys.platform == "darwin":
        from utils import macos_discovery
        return macos_discovery
    return x11_discovery

class WindowManager(QObject):
    window_ids_updated = Signal(list)
    active_window_changed = Signal(str)
    window_geometry_updated = Signal()
    # The per-slot 2x2 cluster cell (0=TL,1=TR,2=BL,3=BR) changed without the
    # window LIST changing - e.g. two stacked windows move from the right column
    # to the left (dense order stays [top,bottom] but cells flip {1,3}->{0,2}).
    # window_ids_updated does NOT fire then, so the card layout listens to this to
    # re-route content into the matching cell shells.
    cell_assignment_changed = Signal(list)

    POLL_INTERVAL = 0.1

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager

        self.ttr_window_ids = []
        # Per-card-slot 2x2 cluster cell (length 4 bijection of 0..3): slot i's
        # window sits in cell slot_cells[i]; unused slots hold the empty cells.
        self.slot_cells: list[int] = [0, 1, 2, 3]
        self.window_games: dict[str, str] = {}  # window_id -> "ttr" | "cc"
        self.window_geometry: dict[str, tuple[int, int, int, int]] = {}
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
        # Don't run assign_windows() synchronously on the caller's thread —
        # this is invoked from the GUI thread on service start, and the X11
        # tree walk inside can block for 100ms-several seconds on Wayland
        # under load. The poll loop will pick up windows within ~2s on its
        # own.

    def disable_detection(self):
        self._detection_enabled = False
        with self._lock:
            self._active_id = None
            had_ids = bool(self.ttr_window_ids)
            self.ttr_window_ids = []
            self.window_games = {}
            self.window_geometry = {}
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

    def has_game_windows(self) -> bool:
        """Any tracked game window exists (focused or not)."""
        with self._lock:
            return bool(self.ttr_window_ids)

    def count_for_game(self, game: str) -> int:
        """Number of currently-detected windows belonging to `game`."""
        with self._lock:
            return sum(1 for g in self.window_games.values() if g == game)

    def clear_window_ids(self):
        with self._lock:
            self.ttr_window_ids = []
            self.window_games = {}
            self.window_geometry = {}
            snapshot = list(self.ttr_window_ids)
        self.window_ids_updated.emit(snapshot)

    def refresh_geometry(self):
        """Refresh the geometry cache for all currently-tracked windows
        (x11_discovery on Linux, win32_discovery on Windows)."""
        with self._lock:
            wids = list(self.ttr_window_ids)
        backend = _geometry_backend()
        fresh = {}
        for wid in wids:
            g = backend.get_window_geometry(wid)
            if g is not None:
                fresh[wid] = g
        with self._lock:
            # Commit-time guard: detection may have been disabled or the
            # window list changed during the off-lock X queries. Keep only
            # wids STILL tracked so a concurrent cache-clear stays cleared
            # (otherwise this swap would resurrect stale entries).
            fresh = {w: g for w, g in fresh.items()
                     if w in self.ttr_window_ids}
            changed = fresh != self.window_geometry
            self.window_geometry = fresh
        if changed:
            # Resizes do not change the window LIST, so click sync needs its
            # own signal to re-check aspect compatibility (live mismatch
            # pause/recovery; see spec).
            self.window_geometry_updated.emit()

    def get_window_geometry(self, wid: str) -> tuple[int, int, int, int] | None:
        """Cached client-window geometry, with an on-demand live query as
        fallback so per-gesture snapshots are never stale-or-missing.
        Non-None is NOT a liveness/membership test — untracked windows can
        still resolve via the live query (returned uncached)."""
        with self._lock:
            cached = self.window_geometry.get(wid)
        if cached is not None:
            return cached
        g = _geometry_backend().get_window_geometry(wid)
        if g is not None:
            with self._lock:
                # Cache only tracked windows: caching an untracked wid
                # would resurrect it and spuriously fire the change signal
                # on the next refresh.
                if wid in self.ttr_window_ids:
                    self.window_geometry[wid] = g
        return g

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
            elif sys.platform == "darwin":
                # macos_discovery.get_active_window_id() touches CGWindowList /
                # NSWorkspace and is not internally guarded the way
                # x11_discovery is, so wrap it like the win32 branch: a transient
                # CG/AppKit error must not crash the poll thread.
                try:
                    from utils import macos_discovery
                    current_active = macos_discovery.get_active_window_id()
                except Exception:
                    current_active = None
            else:
                current_active = x11_discovery.get_active_window_id()
                
            with self._lock:
                self._active_id = current_active
                
            if current_active != last_active:
                self.active_window_changed.emit(current_active or "")
                last_active = current_active

            # Periodically re-assign windows (e.g. every 2 seconds) just in case
            now = time.monotonic()
            if now - last_assign_time > 2.0:
                self.assign_windows()
                self.refresh_geometry()
                last_assign_time = now

            time.sleep(self.POLL_INTERVAL)

    def get_active_window(self):
        with self._lock:
            return self._active_id

    def assign_windows(self):
        """Detect TTR/CC windows and order them by 2x2 cluster cell.

        Each platform branch collects the candidate window ids (in detection
        order); a shared post-step (_order_wids_by_cell) maps each window to its
        on-screen quadrant cell (TL/TR/BL/BR) so card slot i shows the window in
        cell i. This replaces the old pure left-to-right (x) sort, which scrambled
        the cards for any non-row arrangement.
        """
        if not self._detection_enabled:
            return

        registry = GameRegistry.instance()
        game_by_wid: dict[str, str] = {}

        def _accept_candidate_window(wid: str) -> bool:
            game, confirmed = registry.classify_window_for_filtering(wid)
            return not confirmed or game is not None

        wids: list[str] = []
        import sys
        if sys.platform == "win32":
            try:
                import win32gui
                import win32con

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
                            wids.append(wid)
                            game_by_wid[wid] = (
                                "ttr" if "Toontown Rewritten" in title else "cc"
                            )
                win32gui.EnumWindows(enum_windows_proc, 0)
            except Exception:
                wids = []
        elif sys.platform == "darwin":
            try:
                from utils import macos_discovery
                for wid, game in macos_discovery.find_game_windows():
                    if not _accept_candidate_window(wid):
                        continue
                    wids.append(wid)
                    game_by_wid[wid] = game
            except Exception:
                wids = []
        else:
            try:
                for wid, game in x11_discovery.find_game_windows():
                    if not _accept_candidate_window(wid):
                        continue
                    wids.append(wid)
                    game_by_wid[wid] = game
            except Exception:
                wids = []

        ordered, slot_cells = self._assign_cells_to_wids(wids)
        new_ids = ordered[:16]

        with self._lock:
            changed = new_ids != self.ttr_window_ids
            cells_changed = slot_cells != self.slot_cells
            if changed:
                self.ttr_window_ids = list(new_ids)
            if cells_changed:
                self.slot_cells = list(slot_cells)
            self.window_games = {
                wid: game_by_wid[wid] for wid in new_ids if wid in game_by_wid
            }
            snapshot = list(self.ttr_window_ids)
            cells_snapshot = list(self.slot_cells)
        if changed:
            self.window_ids_updated.emit(snapshot)
        if cells_changed:
            # Geometry-only cell changes (dense list unchanged) reach the layout
            # only through this signal; window_ids_updated would not fire.
            self.cell_assignment_changed.emit(cells_snapshot)

    def _assign_cells_to_wids(self, wids):
        """Return ``(ordered_wids, slot_cells)`` for the detected windows.

        ordered_wids: ids ordered by their 2x2 cluster cell (0=TL, 1=TR, 2=BL,
        3=BR) so card slot i shows the window in cell i. Dedupes preserving first
        occurrence. Each window's center comes from the geometry backend; the pure
        ``assign_window_cells`` does the matching. Windows whose geometry is
        unavailable, and any beyond the four placed, keep detection order AFTER the
        placed four, so an odd/partial set never drops a real window.

        slot_cells: a length-4 bijection of cells - slot i's window sits in cell
        slot_cells[i]; the unused slots hold the remaining (empty) cells. For
        contiguous fills (4-window, side-by-side, 2-top-1-bottom) this is the
        identity [0,1,2,3]; a vertical stack gives [0,2,1,3], etc.
        """
        seen: list[str] = []
        for w in wids:
            if w not in seen:
                seen.append(w)
        if not seen:
            return [], [0, 1, 2, 3]
        backend = _geometry_backend()
        centers = []
        for w in seen:
            try:
                g = backend.get_window_geometry(w)
            except Exception:
                g = None
            if g is None:
                centers.append(None)
            else:
                x, y, cw, ch = g
                centers.append((x + cw // 2, y + ch // 2))
        known = [i for i, c in enumerate(centers) if c is not None]
        cells = assign_window_cells([centers[i] for i in known])
        cell_of = {i: cells[pos] for pos, i in enumerate(known)}

        def _key(i):
            c = cell_of.get(i, -1)
            if c is not None and c >= 0:
                return (0, c, i)   # placed: grouped first, ordered by cell
            return (1, 0, i)       # unknown geometry / extras: detection order, last

        ordered = [seen[i] for i in sorted(range(len(seen)), key=_key)]

        placed_cells = sorted(c for c in cell_of.values() if c is not None and c >= 0)
        empty_cells = [c for c in range(4) if c not in placed_cells]
        slot_cells = (placed_cells + empty_cells)[:4]
        while len(slot_cells) < 4:  # belt: placed+empty already == 4
            slot_cells.append(len(slot_cells))
        return ordered, slot_cells

    def _order_wids_by_cell(self, wids):
        """Detected window ids ordered by 2x2 cluster cell (just the ordered ids;
        see _assign_cells_to_wids for the slot->cell bijection)."""
        return self._assign_cells_to_wids(wids)[0]

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
