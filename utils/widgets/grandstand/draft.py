"""The account sheet's edit draft (spec §2; handoff §6.2, account half).

Pure: no Qt. The sheet's fields write into one of these, the view validates
it on Save, LaunchTab performs the write. Cancel drops it — nothing here
persists, and nothing here reads a store.
"""
from __future__ import annotations

from dataclasses import dataclass

MODE_ADD = "add"
MODE_EDIT = "edit"

# Verbatim from handoff §4.4.
USERNAME_REQUIRED = "Username is required"
PASSWORD_REQUIRED = "Password is required"


@dataclass
class AccountDraft:
    """One account's editable half. `keyring_has_password` is whether the
    keyring returned a password at open time; `keyring_readable` is whether
    it could be asked at all (spec §4 "Keyring unavailable"). The two are
    distinct: an unreadable keyring may well hold a password, so a blank
    field must keep it rather than demand a new one."""
    id: str                     # "" in add mode
    game: str
    mode: str                   # MODE_ADD | MODE_EDIT
    label: str = ""
    username: str = ""
    password: str = ""
    keyring_has_password: bool = False
    keyring_readable: bool = True

    @property
    def display_name(self) -> str:
        return self.label or self.username or ""

    def password_required(self) -> bool:
        """Always in add mode; in edit mode only when the keyring was read and
        holds nothing — otherwise blank means "keep the current one"."""
        if self.mode == MODE_ADD:
            return True
        return self.keyring_readable and not self.keyring_has_password

    def validate(self) -> dict[str, str]:
        """Field -> message. Empty when the draft may be saved."""
        errors: dict[str, str] = {}
        if not self.username.strip():
            errors["username"] = USERNAME_REQUIRED
        if self.password_required() and not self.password.strip():
            errors["password"] = PASSWORD_REQUIRED
        return errors


def unique_toons(records: list) -> list:
    """Collapse rename ghosts (spec §3): two records on one account with an
    identical DNA are one toon renamed, and the first in store order — the
    store inserts new records at index 0, so the newest name — wins. CC
    records carry dna == "" and are never merged. Returns a new list."""
    seen: set[str] = set()
    out = []
    for rec in records:
        dna = getattr(rec, "dna", "") or ""
        if dna:
            if dna in seen:
                continue
            seen.add(dna)
        out.append(rec)
    return out


def shown_record(records: list, primary_name):
    """The record an account shows on the launcher: its primary while that
    name is still known, else the newest. Mirrors RecentToonsStore.get so the
    sheet, the browser and the roster card agree about the same toon."""
    if not records:
        return None
    if primary_name:
        for rec in records:
            if rec.toon_name == primary_name:
                return rec
    return records[0]
