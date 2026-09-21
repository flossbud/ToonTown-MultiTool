"""What a widget asks: `pixmap_for(game, toon, pose)`. Sync, from disk, with
a small decoded-pixmap LRU. Consumers repaint on `render_landed` (their pose)
and `set_promoted` (always). `tier == "previous"` means the toon's last
complete look is being shown while a newer outfit downloads -- the user's
notion, which the facade owns; the store's tier only names the slot served."""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Iterable, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage, QPixmap

from utils.render_prefetcher import RenderPrefetcher
from utils.toon_render_store import ToonRenderStore

PREVIOUS_LOOK_TOOLTIP = "Showing previous look — new render pending."
_LRU_MAX = 64


def make_default(cache_root: str) -> "ToonRenders":
    store = ToonRenderStore(cache_root)
    return ToonRenders(store, RenderPrefetcher(store))


class ToonRenders(QObject):
    _instance: Optional["ToonRenders"] = None
    _lock = threading.Lock()

    def __init__(self, store: ToonRenderStore, prefetcher: RenderPrefetcher,
                 parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.prefetcher = prefetcher
        self.render_landed = prefetcher.render_landed
        self.set_promoted = prefetcher.set_promoted
        self.breaker_changed = prefetcher.breaker_changed
        self._lru: "OrderedDict[str, QPixmap]" = OrderedDict()
        # Landing a pose never clears the LRU: a render is a pure function of its
        # DNA, a file at a given path is written once, and the only path ever
        # rewritten is a current set's file after invalidate() -- which already
        # clears the LRU below.
        prefetcher.set_promoted.connect(lambda g, n: self._lru.clear())
        # discovered() fires on every poll tick for every game window (every
        # few seconds, forever) with the same (game, name, dna); memoise so a
        # repeat costs nothing beyond a dict lookup instead of a manifest read.
        self._seen: dict[tuple[str, str], str] = {}

    # ── singleton ─────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "ToonRenders":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    from utils.build_flavor import config_dir
                    cls._instance = make_default(os.path.join(config_dir(), "rendition_cache"))
        return cls._instance

    @classmethod
    def install_for_tests(cls, obj: Optional["ToonRenders"]) -> None:
        cls._instance = obj

    # ── consumer API ──────────────────────────────────────────────────────

    def pixmap_for(self, game: str, name: str, pose: str) -> Optional[tuple[QPixmap, str]]:
        hit = self.store.lookup(game, name, pose)
        if hit is None:
            self.want(game, name, pose)
            return None
        path, tier = hit
        # The store's "current" is the slot served. To the user it is the
        # previous look whenever a newer outfit (the candidate) is pending.
        if tier == "current" and self.store.candidate_dna(game, name):
            tier = "previous"
        pm = self._lru.get(path)
        if pm is None:
            # QPixmap(path) consults Qt's own name+mtime+size decode cache, which
            # can serve stale pixels after invalidate() rewrites this same path
            # within the same wall-clock second; QImage has no such cache.
            img = QImage(path)
            pm = QPixmap.fromImage(img)
            if pm.isNull():
                # Signature passed but the decoder did not: treat as missing so
                # the prefetcher fetches it again rather than serving a blank.
                try:
                    os.remove(path)
                except OSError:
                    pass
                self.want(game, name, pose)
                return None
            self._lru[path] = pm
            if len(self._lru) > _LRU_MAX:
                self._lru.popitem(last=False)
        else:
            self._lru.move_to_end(path)
        return pm, tier

    def want(self, game: str, name: str, pose: str) -> None:
        self.prefetcher.want(game, name, pose)

    def discovered(self, game: str, name: str, dna: str) -> None:
        key = (game, name)
        if self._seen.get(key) == dna:
            return
        self._seen[key] = dna
        self.prefetcher.discovered(game, name, dna)

    def sweep(self, toons: Iterable[tuple[str, str, str]]) -> None:
        self.prefetcher.sweep(toons)

    def invalidate(self, game: str, name: str) -> None:
        # Not cleared here: the prefetcher re-queues the invalidated DNA
        # itself, so a later identical discovered() call has nothing to add.
        self._lru.clear()
        self.prefetcher.invalidate(game, name)

    # ── startup ───────────────────────────────────────────────────────────

    def _remembered(self, settings_manager) -> list[tuple[str, str, str]]:
        from utils.recent_toons import RecentToonsStore
        return [(rec.game, rec.toon_name, rec.dna)
                for _aid, rec in RecentToonsStore(settings_manager).all_records()
                if rec.dna]

    def import_once(self, settings_manager, flat_dir: str) -> int:
        """First run only: copy remembered toons' renders out of the legacy
        flat cache. A marker file makes it idempotent."""
        marker = os.path.join(self.store.toons_root(), ".imported")
        if os.path.exists(marker):
            return 0
        n = self.store.import_flat_cache(flat_dir, self._remembered(settings_manager))
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w") as f:
                f.write("1\n")
        except OSError:
            pass
        return n

    def sweep_remembered(self, settings_manager) -> int:
        toons = self._remembered(settings_manager)
        self.sweep(toons)
        return len(toons)
