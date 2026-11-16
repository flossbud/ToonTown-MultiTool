"""What the Accounts sheet shows, and the words it uses. No Qt.

An ``AccountInfo`` is one saved account with its login state and the toons
seen on it; the sheet renders these and nothing else. The copy functions
hold every sentence of the design so a test can read them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

GAMES = ("ttr", "cc")
GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
GAME_SHORT = {"ttr": "TTR", "cc": "CC"}
GAME_COLORS = {"ttr": "#4A8FE7", "cc": "#F26D21"}
IDENTITY = "#0077ff"

MAX_ACCOUNTS_PER_GAME = 16
TOON_SLOTS = 6

LOGIN_SAVED = "saved"
LOGIN_NONE = "none"
LOGIN_FAILED = "failed"

# What the login form is for.
FORM_ADD_ACCOUNT = "add_account"
FORM_EDIT = "edit"
FORM_FIX = "fix"
FORM_ADD_LOGIN = "add_login"


@dataclass(frozen=True)
class ToonInfo:
    name: str
    game: str
    dna: str = ""
    species: str | None = None
    laff: int | None = None
    max_laff: int | None = None
    accent: str | None = None
    played_at: float | None = None


@dataclass(frozen=True)
class AccountInfo:
    id: str
    game: str
    username: str
    label: str = ""
    login: str = LOGIN_NONE
    failed_reason: str | None = None
    running: bool = False
    toons: tuple = field(default_factory=tuple)     # ToonInfo, most recent first
    primary_name: str | None = None

    @property
    def title(self) -> str:
        return self.label or self.username

    @property
    def shown_toons(self) -> tuple:
        """The toons the sheet has slots for: the primary always, then the
        most recent, ``TOON_SLOTS`` at most."""
        toons = list(self.toons)
        primary = self.primary
        if primary is not None and primary not in toons[:TOON_SLOTS]:
            toons.remove(primary)
            toons.insert(TOON_SLOTS - 1, primary)
        return tuple(toons[:TOON_SLOTS])

    @property
    def primary(self):
        """The toon this account shows on the launcher: the starred one while
        it is still known, else the most recent."""
        if not self.toons:
            return None
        for toon in self.toons:
            if toon.name == self.primary_name:
                return toon
        return self.toons[0]


# ── Copy ───────────────────────────────────────────────────────────────────

def sheet_sub(total_accounts: int, keyring_available: bool = True) -> str:
    noun = "account" if total_accounts == 1 else "accounts"
    if not keyring_available:
        return f"{total_accounts} {noun} · logins cannot be saved on this system"
    return f"{total_accounts} {noun} · logins are kept in your system keyring"


def card_meta(count: int) -> str:
    return f"{count} of {MAX_ACCOUNTS_PER_GAME} accounts"


def toons_meta(count: int) -> str:
    return f"{min(count, TOON_SLOTS)} of {TOON_SLOTS}"


def account_sub(account: AccountInfo) -> str:
    """The row's second line. The gold star before a toon's name is drawn
    by the row; this is the text after it."""
    primary = account.primary
    if primary is None:
        return "No toons seen yet · launch once to discover them"
    return f"{primary.name} · {min(len(account.toons), TOON_SLOTS)} of {TOON_SLOTS} toons"


def status_text(account: AccountInfo) -> str:
    if account.running:
        return "Running"
    return {LOGIN_SAVED: "Login saved", LOGIN_FAILED: "Login failed"}.get(
        account.login, "Asks at launch")


def add_account_text(game: str) -> str:
    return f"Add {GAME_SHORT[game]} account"


def account_page_sub(account: AccountInfo) -> str:
    return f"{GAME_NAMES[account.game]} account"


def login_line(account: AccountInfo) -> str:
    if account.login == LOGIN_FAILED:
        return "The last sign-in was rejected. Check the password."
    if account.login == LOGIN_SAVED:
        return "Password saved in your system keyring"
    return "No saved login. You will be asked when you launch."


def login_buttons(account: AccountInfo) -> tuple:
    """(primary button label, form mode, has reset) for the login row."""
    if account.login == LOGIN_FAILED:
        return ("Fix login", FORM_FIX, True)
    if account.login == LOGIN_SAVED:
        return ("Edit login", FORM_EDIT, True)
    return ("Add login", FORM_ADD_LOGIN, False)


def form_title(mode: str, game: str) -> str:
    return {
        FORM_ADD_ACCOUNT: f"Add a {GAME_NAMES[game]} account",
        FORM_EDIT: "Edit login",
        FORM_FIX: "Fix login",
        FORM_ADD_LOGIN: "Add login",
    }[mode]


def form_primary_text(mode: str) -> str:
    return "Add account" if mode == FORM_ADD_ACCOUNT else "Save login"


KEEP_IN_KEYRING = "Keep in system keyring"
KEYRING_UNAVAILABLE = "Credential storage unavailable. You will type it each launch."
USERNAME_REQUIRED = "Username is required"

TOONS_NOTE = ("The star picks the toon this account shows on the launcher. "
              "Each toon keeps its own look.")
NO_TOONS_NOTE = ("No toons seen yet. Launch this account once and play a toon; "
                 "it shows up here.")
EMPTY_SLOT = "Empty slot"
EMPTY_SLOT_SUB = "Shows up after you play this toon"

LABEL_HELP = "Optional name shown instead of the username."
LABEL_PLACEHOLDER = "e.g. Gag grind alt"
REMOVE_HELP = "Takes it off the launcher. Toon looks are kept."


def forget_question(account: AccountInfo) -> str:
    return f"Forget the saved login for {account.username}?"


FORGET_DETAIL = ("The password is removed from your keyring. You will be asked "
                 "for it the next time you launch.")


def remove_question(account: AccountInfo) -> str:
    return f"Remove {account.title} from the launcher?"


REMOVE_DETAIL = "The saved login is forgotten too. Toon looks are kept."


def toon_line(toon: ToonInfo) -> str:
    """"Duck · 96 laff", or whichever half is known."""
    parts = []
    if toon.species:
        parts.append(toon.species.strip().capitalize())
    if toon.laff is not None:
        parts.append(f"{toon.laff} laff")
    return " · ".join(parts)


def played_text(played_at: float | None, now: float | None = None) -> str:
    """"played yesterday", "played 4d ago"; empty when it was never stamped."""
    if played_at is None:
        return ""
    now = time.time() if now is None else now
    seconds = max(0.0, now - played_at)
    days = int(seconds // 86400)
    if days <= 0:
        return "played today"
    if days == 1:
        return "played yesterday"
    if days < 14:
        return f"played {days}d ago"
    if days < 60:
        return f"played {days // 7}w ago"
    if days < 365:
        return f"played {days // 30}mo ago"
    return f"played {days // 365}y ago"


def toon_played_line(toon: ToonInfo, is_primary: bool, now: float | None = None) -> str:
    played = played_text(toon.played_at, now)
    if is_primary:
        return f"Primary · {played}" if played else "Primary"
    return played
