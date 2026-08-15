"""Theme-aware colours for the Grandstand launcher (2026-08-14 spec).

One pure function per surface. Dark branches return the design handoff's §9
token literals byte-for-byte so the reference build and the app agree; the
light branch is a later task (spec Q8) and lives behind the same signatures,
which is why every function already takes `is_dark`.

Token comments name the handoff variable so a token rename is greppable.
Leaf module: QColor + utils.color_math only.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

from utils.color_math import with_alpha

# --game-ttr / --game-cc, and the per-game identity the selector + hero share.
_GAME = {
    "ttr": {"identity": "#4A8FE7", "card_bg": "#14283d", "hero": "#1d4a7a",
            "scrim": (20, 40, 61)},
    "cc":  {"identity": "#F26D21", "card_bg": "#3a1e0e", "hero": "#7a3a12",
            "scrim": (58, 30, 14)},
}

# Corporate Clash's skyline art is natively blue-teal. Handoff §4.1b requires a
# second warm gradient over it so the largest element on screen still reads
# orange; TTR's pattern art needs none.
CC_WARM_SCRIM = (with_alpha("#f26d21", 0.50), with_alpha("#96370c", 0.55))


def _rgba(rgb: tuple[int, int, int], a: float) -> QColor:
    c = QColor(*rgb)
    c.setAlphaF(a)
    return c


def game_accent(game: str) -> str:
    """The game's identity hex. Public because `model.py` needs it as the last
    accent fallback, and a second copy of these two literals would let the
    resolved accent drift from the painted one."""
    return _GAME[game]["identity"]


def game_card(game: str, active: bool, is_dark: bool) -> dict:
    """Game selector card (handoff §4.1a). Inactive cards desaturate and drop
    their backdrop art to .34; active cards take the game's identity border."""
    g = _GAME[game]
    return {
        "bg": QColor(g["card_bg"]) if active else QColor("#252525"),  # --bg-card
        "border": QColor(g["identity"]) if active else QColor("#363636"),
        "inset": with_alpha(g["identity"], 0.35) if active else None,
        "name_ink": QColor("#ffffff"),
        "meta_ink": QColor("#888888"),                       # --text-muted
        "art_opacity": 0.72 if active else 0.34,
        "saturation": 1.0 if active else 0.45,
    }


def hero_base(game: str, is_dark: bool) -> QColor:
    """Flat fill under the hero art — also the fallback if the art fails to
    load (spec §7)."""
    # Theme-independent today: hero art sits under white text in either theme.
    # The parameter keeps light mode a value change, not a signature change.
    return QColor(_GAME[game]["hero"])


def hero_scrim(game: str, is_dark: bool) -> list[tuple[float, QColor]]:
    """Left-to-right darkening over the hero backdrop so the copy column stays
    legible (handoff §4.1b). Stops are (position, colour) for a 90° gradient."""
    # Theme-independent today: hero art sits under white text in either theme.
    # The parameter keeps light mode a value change, not a signature change.
    rgb = _GAME[game]["scrim"]
    if game == "cc":
        return [(0.0, _rgba(rgb, 0.90)), (0.56, _rgba(rgb, 0.50)),
                (1.0, _rgba(rgb, 0.24))]
    return [(0.0, _rgba(rgb, 0.90)), (0.56, _rgba(rgb, 0.46)),
            (1.0, _rgba(rgb, 0.14))]


def play_button(enabled: bool, is_dark: bool) -> dict:
    """The one CTA. Disabled loses the drop shadow entirely (handoff §4.1b)."""
    if not enabled:
        return {"bg": with_alpha("#ffffff", 0.12),
                "border": with_alpha("#ffffff", 0.22),
                "ink": with_alpha("#ffffff", 0.55), "shadow": None}
    return {"bg": QColor("#d4a017"),            # --v2-yellow
            "border": QColor("#e8c14d"),        # --v2-yellow-b
            "ink": QColor("#231a04"),
            "shadow": with_alpha("#000000", 0.28)}


def panel(is_dark: bool) -> dict:
    """Chooser panel and any card-level surface."""
    return {"bg": QColor("#252525"),            # --bg-card
            "border": QColor("#363636")}        # --border-card


def card_surface(accent: str, selected: bool, is_dark: bool) -> dict:
    """Roster card body: an accent-tinted vertical wash (handoff §4.1d)."""
    return {
        "top": with_alpha(accent, 0.26),
        "bot": with_alpha("#000000", 0.30),
        "border": QColor("#3399ff") if selected else QColor("#363636"),
    }


def card_ink(selected: bool, is_dark: bool) -> dict:
    return {"name": QColor("#ffffff"),
            "user": QColor("#888888"),          # --text-muted
            "foot": QColor("#9fc9f5") if selected else QColor("#888888")}


def control_chip(hover: bool, is_dark: bool) -> dict:
    """Pencil / gear / ribbon backing."""
    return {"bg": with_alpha("#000000", 0.55 if hover else 0.35),
            "ink": QColor("#ffffff") if hover else QColor("#888888")}


# Card footer status colours, keyed by the LoginState the tile already uses.
_STATUS = {
    "running":    ("#56d66a", "#56c856"),   # --green-border / --status-dot-active
    "failed":     ("#ff7575", "#ff7575"),   # error
    "need_2fa":   ("#3399ff", "#3399ff"),   # --blue-border
    "queued":     ("#e8c14d", "#e8c14d"),   # --v2-yellow-b
    "logging_in": ("#e8c14d", "#e8c14d"),
    "launching":  ("#e8c14d", "#e8c14d"),
    "loading":    ("#3399ff", "#3399ff"),
}


def status_ink(state: str, is_dark: bool) -> dict:
    """Footer text + dot for one card state. Unknown/idle falls to muted."""
    text, dot = _STATUS.get(state, ("#888888", "#555555"))  # --text-muted/-idle
    return {"text": QColor(text), "dot": QColor(dot)}


def head_link(enabled: bool, gold: bool, is_dark: bool) -> QColor:
    """Chooser head-row links. `Clear main` is gold; all disable to
    --text-disabled with no underline (handoff §4.1c)."""
    if not enabled:
        return QColor("#666666")                # --text-disabled
    return QColor("#e8c14d") if gold else QColor("#888888")


def advisory_strip(is_dark: bool) -> dict:
    """Slim non-blocking credential bar above the selector (spec Q6)."""
    return {"bg": with_alpha("#e8c14d", 0.14),
            "border": with_alpha("#e8c14d", 0.34),
            "ink": QColor("#e8c14d")}


def shelf_head_ink(is_dark: bool) -> dict:
    """Chooser head row: uppercase title and its explanatory sub-line."""
    return {"title": QColor("#bbbbbb"),        # --text-secondary
            "sub": QColor("#888888")}          # --text-muted


def add_tile(is_dark: bool) -> dict:
    """The dashed 'Add account' tile that always ends the shelf."""
    return {"ink": QColor("#888888"),          # --text-muted
            "border": QColor("#555555")}       # --border-light


def ribbon(selected: bool, is_dark: bool) -> dict:
    """Card ribbon: '+' to add, then the toon's place on stage once selected
    (handoff §4.1d)."""
    if selected:
        return {"bg": QColor("#0077ff"),       # --blue
                "border": QColor("#3399ff"),   # --blue-border
                "ink": QColor("#ffffff")}
    return {"bg": with_alpha("#000000", 0.35),
            "border": with_alpha("#ffffff", 0.18),
            "ink": QColor("#888888")}          # --text-muted


def lineup_ink(is_dark: bool) -> dict:
    """Surfaces of the hero's toon lineup. Like `hero_ink`, these sit on game
    artwork under a scrim rather than on an app surface, so they do not vary by
    theme. The accent ring around a cameo is NOT here — it comes from the
    account's own accent."""
    return {"cameo_disc": with_alpha("#000000", 0.30),
            "placeholder_border": with_alpha("#ffffff", 0.40),
            "placeholder_ink": with_alpha("#ffffff", 0.67)}


def hero_ink(is_dark: bool) -> dict:
    """Copy that sits directly on the hero artwork. White regardless of theme:
    the hero is game art under a darkening scrim in both light and dark, so this
    ink answers to the scrim, not to the app surface."""
    return {"greeting": QColor("#ffffff"),
            "names": with_alpha("#ffffff", 0.82),
            "blocked": QColor("#ffffff")}


def hero_ghost_button(is_dark: bool) -> dict:
    """Quiet buttons that sit on top of the hero art — the official-launcher
    escape hatch and the blocked-mode action. They read against artwork, not
    against a token surface, so their alphas are deliberate."""
    return {"bg": with_alpha("#000000", 0.26),
            "border": with_alpha("#ffffff", 0.24),
            "ink": QColor("#ffffff")}
