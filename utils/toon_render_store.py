"""Per-toon render cache on disk. Pure Python: no Qt, no network, no threads.

Layout (one folder per toon, up to two complete DNA sets):

    <root>/toons/<game>/<toon-slug>/
        manifest.json
        <current-dna>/   portrait.png ... head.png
        <previous-dna>/  the last complete set, kept until a newer one is whole

A DNA becomes *current* only once every pose in the contract is on disk and
PNG-valid; until then the previous complete set keeps serving, so a
half-fetched outfit is never visible. An outfit the origin refuses for every
pose can never complete, so it is dropped rather than left pending. Nothing
expires by age: a render is a pure function of its DNA.
See docs/superpowers/specs/2026-09-21-toon-render-cache-design.md.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Iterable, Optional

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MANIFEST = "manifest.json"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "toon"


class ToonRenderStore:
    def __init__(self, root: str, poses: Optional[tuple[str, ...]] = None) -> None:
        if poses is None:
            from utils.rendition_poses import POSE_NAMES
            poses = tuple(POSE_NAMES)
        self._root = root
        self._poses = tuple(poses)
        self._warned: set[str] = set()

    # ── paths ─────────────────────────────────────────────────────────────

    @property
    def poses(self) -> tuple[str, ...]:
        return self._poses

    def toons_root(self) -> str:
        return os.path.join(self._root, "toons")

    def toon_dir(self, game: str, name: str) -> str:
        """The toon's folder, creating it and its manifest on first use.
        Slugs collide ("Blue Cat" / "blue cat"); the manifest carries the exact
        name, so a collision gets a numeric suffix rather than a shared folder."""
        base = os.path.join(self._root, "toons", game)
        slug = _slugify(name)
        n = 1
        while True:
            d = os.path.join(base, slug if n == 1 else f"{slug}-{n}")
            m = self._read_manifest(d)
            if m is None:
                os.makedirs(d, exist_ok=True)
                self._write_manifest(d, self._blank(game, name))
                return d
            if m.get("name") == name:
                return d
            n += 1

    def path_for(self, game: str, name: str, dna: str, pose: str) -> str:
        d = os.path.join(self.toon_dir(game, name), dna)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{pose}.png")

    # ── manifest ──────────────────────────────────────────────────────────

    @staticmethod
    def _blank(game: str, name: str) -> dict:
        return {"name": name, "game": game, "current": None, "previous": None,
                "candidate": None, "sets": {}, "updated": None}

    def _read_manifest(self, d: str) -> Optional[dict]:
        try:
            with open(os.path.join(d, _MANIFEST), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_manifest(self, d: str, m: dict) -> None:
        m["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = os.path.join(d, _MANIFEST + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=1, sort_keys=True)
            os.replace(tmp, os.path.join(d, _MANIFEST))
        except OSError as exc:
            self._warn(f"manifest write failed for {d}: {exc}")

    def _manifest(self, game: str, name: str) -> tuple[str, dict]:
        d = self.toon_dir(game, name)
        return d, (self._read_manifest(d) or self._blank(game, name))

    def _warn(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            print(f"[ToonRenderStore] {msg}")

    # ── file checks ───────────────────────────────────────────────────────

    def _valid_png(self, path: str) -> bool:
        """Absent is a normal state (not logged). Present-but-unreadable or
        present-but-not-a-PNG is a disk fault: logged once, read as absent."""
        try:
            with open(path, "rb") as f:
                ok = f.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
        except FileNotFoundError:
            return False
        except OSError as exc:
            self._warn(f"unreadable render {path}: {exc}")
            return False
        if not ok:
            self._warn(f"not a PNG, ignored: {path}")
        return ok

    def _set_complete(self, d: str, m: dict, dna: Optional[str]) -> bool:
        """Every pose is on disk OR the server refused it (a 4xx: it will never
        render, and waiting would strand the toon on its previous look). At
        least one pose must actually be on disk."""
        if not dna:
            return False
        failed = set(m.get("sets", {}).get(dna, {}).get("failed", []))
        present = [self._valid_png(os.path.join(d, dna, f"{p}.png")) for p in self._poses]
        return any(present) and all(
            ok or p in failed for ok, p in zip(present, self._poses))

    # ── sets ──────────────────────────────────────────────────────────────

    def current_dna(self, game: str, name: str) -> Optional[str]:
        return self._manifest(game, name)[1].get("current")

    def candidate_dna(self, game: str, name: str) -> Optional[str]:
        return self._manifest(game, name)[1].get("candidate")

    def note_dna(self, game: str, name: str, dna: str) -> str:
        """Record a freshly observed DNA. Returns "current" when nothing needs
        fetching (it already is, or it was the previous set and is swapped
        straight back), else "candidate"."""
        d, m = self._manifest(game, name)
        if dna == m.get("current"):
            return "current"
        if dna == m.get("previous") and self._set_complete(d, m, dna):
            # Swapping back supersedes any outfit that was mid-download too.
            self._drop_set(d, m, m.get("candidate"))
            m["previous"], m["current"] = m["current"], dna
            m["candidate"] = None
            self._write_manifest(d, m)
            return "current"
        if dna != m.get("candidate"):
            # An outfit that was tried and superseded before it finished would
            # otherwise sit on disk forever.
            self._drop_set(d, m, m.get("candidate"))
            m["candidate"] = dna
            self._set_record(m, dna)
            self._write_manifest(d, m)
        return "candidate"

    @staticmethod
    def _set_record(m: dict, dna: str) -> dict:
        return m["sets"].setdefault(dna, {"landed": [], "failed": []})

    def _drop_set(self, d: str, m: dict, dna: Optional[str]) -> None:
        """Delete a DNA's files unless something still references them."""
        if dna and dna not in (m.get("current"), m.get("previous")):
            shutil.rmtree(os.path.join(d, dna), ignore_errors=True)
            m["sets"].pop(dna, None)

    def mark_landed(self, game: str, name: str, dna: str, pose: str) -> bool:
        d, m = self._manifest(game, name)
        path = os.path.join(d, dna, f"{pose}.png")
        if not self._valid_png(path):          # _valid_png logs the fault itself
            return False
        rec = self._set_record(m, dna)
        if pose not in rec["landed"]:
            rec["landed"].append(pose)
        if pose in rec["failed"]:
            rec["failed"].remove(pose)
        self._write_manifest(d, m)
        return True

    def mark_failed(self, game: str, name: str, dna: str, pose: str) -> None:
        d, m = self._manifest(game, name)
        rec = self._set_record(m, dna)
        if pose not in rec["failed"]:
            rec["failed"].append(pose)
        self._write_manifest(d, m)

    def missing_poses(self, game: str, name: str, dna: str) -> list[str]:
        d, m = self._manifest(game, name)
        failed = set(m["sets"].get(dna, {}).get("failed", []))
        return [p for p in self._poses
                if p not in failed and not self._valid_png(os.path.join(d, dna, f"{p}.png"))]

    def promote_if_complete(self, game: str, name: str) -> bool:
        """Promote the candidate once it is complete. A candidate with nothing
        landed and every pose refused is dead -- it can never satisfy the
        >=1-landed rule -- so it is abandoned here (files and record dropped,
        candidate cleared) instead of pinning the toon on its previous look
        with no way to refresh. Returns True only on a promotion."""
        d, m = self._manifest(game, name)
        cand = m.get("candidate")
        if not cand:
            return False
        rec = m.get("sets", {}).get(cand, {})
        if not rec.get("landed") and set(rec.get("failed", [])) >= set(self._poses):
            self._drop_set(d, m, cand)
            m["candidate"] = None
            self._write_manifest(d, m)
            self._warn(f"{game}/{name}: outfit {cand} refused for every pose; dropped")
            return False
        if not self._set_complete(d, m, cand):
            return False
        older = m.get("previous")
        m["previous"], m["current"], m["candidate"] = m.get("current"), cand, None
        self._drop_set(d, m, older)
        self._write_manifest(d, m)
        return True

    def lookup(self, game: str, name: str, pose: str) -> Optional[tuple[str, str]]:
        d, m = self._manifest(game, name)
        for tier in ("current", "previous"):
            dna = m.get(tier)
            if not dna:
                continue
            path = os.path.join(d, dna, f"{pose}.png")
            if self._valid_png(path):
                return path, tier
        return None

    def invalidate(self, game: str, name: str) -> Optional[str]:
        """User-initiated refresh. If a newer outfit is already on its way,
        that IS the fresh art the user wants: return its DNA so the caller can
        re-prioritise it, and touch nothing — deleting current here would send
        the toon dark if that download stalls. Otherwise drop the current
        set's files and re-queue that DNA as the candidate; previous stays
        intact as the fallback."""
        d, m = self._manifest(game, name)
        cand = m.get("candidate")
        if cand and cand != m.get("current"):
            return cand
        cur = m.get("current")
        if not cur:
            return None
        shutil.rmtree(os.path.join(d, cur), ignore_errors=True)
        m["current"], m["candidate"] = None, cur
        m["sets"][cur] = {"landed": [], "failed": []}
        self._write_manifest(d, m)
        return cur

    # ── migration ─────────────────────────────────────────────────────────

    def import_flat_cache(self, flat_dir: str,
                          toons: Iterable[tuple[str, str, str]]) -> int:
        """One-time copy from the legacy flat layout (`<dna>__<pose>__512.png`)
        for each remembered (game, name, dna). Complete sets promote; partial
        ones become the candidate the startup sweep fills in. Sources are left
        in place — the legacy launcher still reads them until cut-over."""
        if not os.path.isdir(flat_dir):
            return 0
        copied = 0
        for game, name, dna in toons:
            if not dna:
                continue
            if self.note_dna(game, name, dna) == "current":
                continue
            for pose in self._poses:
                src = os.path.join(flat_dir, f"{dna}__{pose}__512.png")
                dst = self.path_for(game, name, dna, pose)
                if self._valid_png(dst) or not self._valid_png(src):
                    continue
                try:
                    shutil.copyfile(src, dst)
                except OSError as exc:
                    self._warn(f"import of {src} failed: {exc}")
                    continue
                if self.mark_landed(game, name, dna, pose):
                    copied += 1
            self.promote_if_complete(game, name)
        return copied
