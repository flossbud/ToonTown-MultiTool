"""Per-account toon history + primary pointer, persisted via settings_manager.

Holds the set of toons TTMT has seen in-world per account (most-recent-first,
deduped by name, capped) with per-toon metadata, plus an optional explicit
"primary" pick. get() resolves to the primary (explicit, else most-recent) so
the emblem radial menu (which reads name/dna) is unaffected.

Persistence key "recent_toons", versioned v2:
  {"_v": 2, "accounts": {aid: {"toons": [rec, ...], "primary": name|None}}}
The legacy v1 flat shape {aid: {toon_name,game,dna}} is migrated on first read.

settings_manager must expose get(key, default)/set(key, value); pass None to
degrade to a no-op (never persists, always empty).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from utils.ttr_dna import parse_dna

_KEY = "recent_toons"
_CAP = 8


@dataclass(frozen=True)
class ToonRecord:
    toon_name: str
    game: str
    dna: str
    laff: int | None = None
    max_laff: int | None = None
    species: str | None = None
    accent: str | None = None


def _rec_from_dict(d: dict) -> ToonRecord | None:
    name = d.get("toon_name")
    game = d.get("game")
    if not isinstance(name, str) or not name or game not in ("ttr", "cc"):
        return None
    return ToonRecord(
        name, game, d.get("dna") if isinstance(d.get("dna"), str) else "",
        d.get("laff") if isinstance(d.get("laff"), int) else None,
        d.get("max_laff") if isinstance(d.get("max_laff"), int) else None,
        d.get("species") if isinstance(d.get("species"), str) else None,
        d.get("accent") if isinstance(d.get("accent"), str) else None,
    )


class RecentToonsStore:
    def __init__(self, settings_manager):
        self._sm = settings_manager

    # persistence
    def _raw(self) -> dict:
        if self._sm is None:
            return {}
        raw = self._sm.get(_KEY, {})
        return raw if isinstance(raw, dict) else {}

    def _doc(self) -> dict:
        """Return the v2 doc, migrating (and persisting) a v1 flat shape once."""
        raw = self._raw()
        if not raw:
            return {"_v": 2, "accounts": {}}
        if raw.get("_v") == 2 and isinstance(raw.get("accounts"), dict):
            # Deep-copy: settings_manager.get() may hand back the same object
            # it stores internally, so mutating it in-place here would corrupt
            # the pre-write snapshot _raw() re-reads for the dirty check below.
            return copy.deepcopy(raw)
        accounts: dict = {}
        for aid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            rec = _rec_from_dict(entry)
            if rec is None:
                continue
            species, accent = (None, None)
            if rec.game == "ttr" and rec.dna:
                species, accent = parse_dna(rec.dna)
            toon = {"toon_name": rec.toon_name, "game": rec.game, "dna": rec.dna,
                    "laff": None, "max_laff": None, "species": species, "accent": accent}
            accounts[aid] = {"toons": [toon], "primary": None}
        doc = {"_v": 2, "accounts": accounts}
        if self._sm is not None:
            self._sm.set(_KEY, doc)
        return doc

    def _write(self, doc: dict) -> None:
        if self._sm is not None:
            self._sm.set(_KEY, doc)

    # reads
    def _account(self, account_id: str) -> dict:
        return self._doc().get("accounts", {}).get(account_id, {})

    def list(self, account_id: str) -> list[ToonRecord]:
        out = []
        for d in self._account(account_id).get("toons", []):
            rec = _rec_from_dict(d) if isinstance(d, dict) else None
            if rec is not None:
                out.append(rec)
        return out

    def primary_name(self, account_id: str) -> str | None:
        p = self._account(account_id).get("primary")
        return p if isinstance(p, str) else None

    def get(self, account_id: str) -> ToonRecord | None:
        toons = self.list(account_id)
        if not toons:
            return None
        p = self.primary_name(account_id)
        if p:
            for r in toons:
                if r.toon_name == p:
                    return r
        return toons[0]

    # writes
    def set_primary(self, account_id: str, toon_name: str) -> None:
        doc = self._doc()
        acct = doc.setdefault("accounts", {}).get(account_id)
        if not acct:
            return
        if any(t.get("toon_name") == toon_name for t in acct.get("toons", [])):
            acct["primary"] = toon_name
            self._write(doc)

    def record(self, account_id: str, toon_name: str, game: str, dna: str = "",
               *, laff=None, max_laff=None, species=None, accent=None) -> None:
        if not isinstance(account_id, str) or not account_id:
            return
        if not isinstance(toon_name, str) or not toon_name:
            return
        if game not in ("ttr", "cc"):
            return
        doc = self._doc()
        acct = doc.setdefault("accounts", {}).setdefault(
            account_id, {"toons": [], "primary": None})
        toons = [t for t in acct.get("toons", []) if isinstance(t, dict)]
        existing = next((t for t in toons if t.get("toon_name") == toon_name), None)
        new = {"toon_name": toon_name, "game": game,
               "dna": dna if isinstance(dna, str) else ""}
        if existing is not None:
            new = {**existing, **new}
            toons.remove(existing)
        for k, v in (("laff", laff), ("max_laff", max_laff),
                     ("species", species), ("accent", accent)):
            if v is not None:
                new[k] = v
            else:
                new.setdefault(k, None)
        toons.insert(0, new)
        del toons[_CAP:]
        acct["toons"] = toons
        if acct.get("primary") and not any(
                t.get("toon_name") == acct["primary"] for t in toons):
            acct["primary"] = None
        if self._raw() == doc:
            return
        self._write(doc)
