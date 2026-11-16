"""Theme-aware colours for the Grandstand launcher (2026-08-14 spec).

One pure function per surface. Dark branches return the design handoff's §9
token literals byte-for-byte so the reference build and the app agree. Light
branches use theme_manager's light tokens of the same name (annotated), so the
roster reads as one surface with the rest of the light app. Surfaces that sit
on game artwork (hero, active game card, lineup) answer to the art and its
scrim, not to the app theme, and have no light branch on purpose.

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
    if active:
        # The active card is game art under white copy in either theme. Its
        # meta line sits on that art, so it is a white alpha, not --text-muted
        # (grey on the TTR blue measured 2.3:1).
        return {
            "bg": QColor(g["card_bg"]),
            "border": QColor(g["identity"]),
            "inset": with_alpha(g["identity"], 0.35),
            "name_ink": QColor("#ffffff"),
            "meta_ink": with_alpha("#ffffff", 0.74),
            "art_opacity": 0.72,
            "saturation": 1.0,
        }
    if is_dark:
        return {
            "bg": QColor("#252525"),                # --bg-card
            "border": QColor("#363636"),            # --border-card
            "inset": None,
            "name_ink": QColor("#ffffff"),
            "meta_ink": QColor("#888888"),          # --text-muted
            "art_opacity": 0.34,
            "saturation": 0.45,
        }
    return {
        "bg": QColor("#ffffff"),                    # bg_card (light)
        "border": QColor("#e2e8f0"),                # border_card (light)
        "inset": None,
        "name_ink": QColor("#334155"),              # text_secondary (light)
        "meta_ink": QColor("#475569"),              # text_muted (light)
        "art_opacity": 0.20,
        "saturation": 0.45,
    }


def game_card_scrim(game: str, is_dark: bool) -> list[tuple[float, QColor]]:
    """Left-to-right wash over the ACTIVE game card's art, in the card's own
    base colour, so the logo and name sit on the game's identity and the art
    opens up to the right (the handoff's selector card). Without it Corporate
    Clash's blue-teal skyline covered the whole card and the orange game read
    as a blue one. Art-facing, so the same in both themes."""
    rgb = QColor(_GAME[game]["card_bg"])
    base = (rgb.red(), rgb.green(), rgb.blue())
    return [(0.0, _rgba(base, 0.92)), (0.45, _rgba(base, 0.62)),
            (1.0, _rgba(base, 0.0))]


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
    if is_dark:
        return {"bg": QColor("#252525"),        # --bg-card
                "border": QColor("#363636")}    # --border-card
    return {"bg": QColor("#ffffff"),            # bg_card (light)
            "border": QColor("#e2e8f0")}        # border_card (light)


def card_surface(accent: str, selected: bool, is_dark: bool) -> dict:
    """Roster card body: an accent-tinted vertical wash (handoff §4.1d)."""
    if is_dark:
        return {
            "top": with_alpha(accent, 0.26),
            "bot": with_alpha("#000000", 0.30),
            "border": QColor("#3399ff") if selected else QColor("#363636"),
        }
    # Light: the same accent wash, falling to a faint slate so the card still
    # has a floor on the white panel instead of dissolving into it.
    return {
        "top": with_alpha(accent, 0.22),
        "bot": with_alpha("#0f172a", 0.05),
        "border": QColor("#0077ff") if selected else QColor("#cbd5e1"),
    }


def card_placeholder(is_dark: bool) -> dict:
    """A card with nothing to draw yet: the dashed ring and the account's
    initial inside it. Quieter than the hero's placeholder, which sits on
    game art; this one sits on the card's own wash."""
    if is_dark:
        return {"ring": with_alpha("#ffffff", 0.26),
                "initial": with_alpha("#ffffff", 0.50)}
    return {"ring": with_alpha("#0f172a", 0.26),
            "initial": with_alpha("#0f172a", 0.46)}


def card_ink(selected: bool, is_dark: bool) -> dict:
    if is_dark:
        return {"name": QColor("#ffffff"),
                "user": QColor("#888888"),      # --text-muted
                "foot": QColor("#9fc9f5") if selected else QColor("#888888")}
    return {"name": QColor("#0f172a"),          # text_primary (light)
            "user": QColor("#475569"),          # text_muted (light)
            "foot": QColor("#0058c0") if selected else QColor("#475569")}


def control_chip(hover: bool, is_dark: bool, enabled: bool = True) -> dict:
    """Pencil / gear / ribbon backing. A disabled chip (the pencil on an
    account with no discovered toon) keeps its backing and drops its ink to
    the disabled text token, so it reads as present but unavailable."""
    if not enabled:
        if is_dark:
            return {"bg": with_alpha("#000000", 0.22),
                    "ink": QColor("#666666")}       # --text-disabled
        return {"bg": with_alpha("#0f172a", 0.04),
                "ink": QColor("#94a3b8")}
    if is_dark:
        return {"bg": with_alpha("#000000", 0.55 if hover else 0.35),
                "ink": QColor("#ffffff") if hover else QColor("#888888")}
    return {"bg": with_alpha("#0f172a", 0.14 if hover else 0.07),
            "ink": QColor("#0f172a") if hover else QColor("#475569")}


def card_star(starred: bool, is_dark: bool) -> dict:
    """Card star chip. Gold once it marks the game-wide main (handoff §4.1d)."""
    if is_dark:
        return {"bg": with_alpha("#000000", 0.35),
                "ink": QColor("#e8c14d") if starred else QColor("#888888")}
    # --v2-yellow is 2.4:1 on white; the starred chip carries a gold fill and
    # a darker gold ink so it still reads as "the gold one" in light.
    if starred:
        return {"bg": with_alpha("#d4a017", 0.24), "ink": QColor("#8a6100")}
    return {"bg": with_alpha("#0f172a", 0.07), "ink": QColor("#475569")}


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


# The same states on a light card. The dark hues are tuned to glow on a dark
# wash and fall under 3:1 on white, so each is the darker step of its hue.
_STATUS_LIGHT = {
    "running":    ("#15803d", "#16a34a"),
    "failed":     ("#c62828", "#dc2626"),
    "need_2fa":   ("#0058c0", "#0077ff"),
    "queued":     ("#8a6100", "#d4a017"),
    "logging_in": ("#8a6100", "#d4a017"),
    "launching":  ("#8a6100", "#d4a017"),
    "loading":    ("#0058c0", "#0077ff"),
}


def status_ink(state: str, is_dark: bool) -> dict:
    """Footer text + dot for one card state. Unknown/idle falls to muted."""
    if is_dark:
        text, dot = _STATUS.get(state, ("#888888", "#555555"))  # --text-muted/-idle
    else:
        text, dot = _STATUS_LIGHT.get(state, ("#475569", "#94a3b8"))
    return {"text": QColor(text), "dot": QColor(dot)}


# Action-button fills, ported verbatim from utils/widgets/account_tile.py:68 so
# both launchers read the same while both exist.
_ACTION_FILL = {
    "loading":  "#e05252",     # Quit
    "queued":   "#e05252",     # Cancel
    "running":  "#e05252",     # Quit
    "need_2fa": "#a763d8",     # Enter 2FA
    "failed":   "#c84e34",     # Retry
}


def card_action(state: str, accent: str, is_dark: bool) -> dict:
    """The card's state-aware action button. States that act on a live session
    carry their own pinned fill; idle falls back to the account's accent, the
    way the tile falls back to the game's."""
    fill = _ACTION_FILL.get(state)
    return {"bg": QColor(fill) if fill else QColor(accent),
            "ink": QColor("#ffffff")}


def head_link(enabled: bool, gold: bool, is_dark: bool) -> QColor:
    """Chooser head-row links. `Clear main` is gold; all disable to
    --text-disabled with no underline (handoff §4.1c)."""
    if is_dark:
        if not enabled:
            return QColor("#666666")            # --text-disabled
        return QColor("#e8c14d") if gold else QColor("#888888")
    if not enabled:
        return QColor("#94a3b8")
    return QColor("#8a6100") if gold else QColor("#475569")


def advisory_strip(is_dark: bool) -> dict:
    """Slim non-blocking credential bar above the selector (spec Q6)."""
    if is_dark:
        return {"bg": with_alpha("#e8c14d", 0.14),
                "border": with_alpha("#e8c14d", 0.34),
                "ink": QColor("#e8c14d")}
    return {"bg": with_alpha("#d4a017", 0.16),
            "border": with_alpha("#d4a017", 0.50),
            "ink": QColor("#6b4b00")}


def shelf_head_ink(is_dark: bool) -> dict:
    """Chooser head row: uppercase title and its explanatory sub-line."""
    if is_dark:
        return {"title": QColor("#bbbbbb"),    # --text-secondary
                "sub": QColor("#888888")}      # --text-muted
    return {"title": QColor("#334155"),        # text_secondary (light)
            "sub": QColor("#475569")}          # text_muted (light)


def add_tile(is_dark: bool) -> dict:
    """The dashed 'Add account' tile that always ends the shelf."""
    if is_dark:
        return {"ink": QColor("#888888"),      # --text-muted
                "border": QColor("#555555")}   # --border-light
    return {"ink": QColor("#475569"),          # text_muted (light)
            "border": QColor("#94a3b8")}


def shelf_scroll(is_dark: bool) -> dict:
    """Shelf scroll chrome (handoff §4.1c). The edge fade is the chooser
    panel's own background dissolving to nothing, so it reads as the panel
    covering the cards rather than as a grey wash of its own."""
    bg = panel(is_dark)["bg"]
    thumb = QColor("#555555") if is_dark else QColor("#cbd5e1")  # --border-light
    return {"thumb": thumb,
            "fade_in": QColor(bg),
            "fade_out": with_alpha(bg.name(), 0.0)}


def ribbon(selected: bool, is_dark: bool) -> dict:
    """Card ribbon: '+' to add, then the toon's place on stage once selected
    (handoff §4.1d)."""
    if selected:
        return {"bg": QColor("#0077ff"),       # --blue
                "border": QColor("#3399ff"),   # --blue-border
                "ink": QColor("#ffffff")}
    if is_dark:
        return {"bg": with_alpha("#000000", 0.35),
                "border": with_alpha("#ffffff", 0.18),
                "ink": QColor("#888888")}      # --text-muted
    return {"bg": with_alpha("#ffffff", 0.80),
            "border": with_alpha("#0f172a", 0.22),
            "ink": QColor("#475569")}          # text_muted (light)


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


# ── Account sheet + toon browser (2026-09-22 spec, sub-project C) ───────────
# Light values are theme_manager's light tokens of the same name (annotated),
# so the sheet reads as one surface with the rest of the light app.


def sheet_surface(is_dark: bool) -> dict:
    """The focus-mode page and the browser's shelf-slot panel."""
    if is_dark:
        return {"bg": QColor("#252525"),            # --bg-card
                "border": QColor("#363636")}        # --border-card
    return {"bg": QColor("#ffffff"),                # bg_card (light)
            "border": QColor("#e2e8f0")}            # border_card (light)


def sheet_ink(is_dark: bool) -> dict:
    """Header title/subtitle, section labels, the preview caption, footer note."""
    if is_dark:
        return {"title": QColor("#bbbbbb"),         # --text-secondary
                "sub": QColor("#888888"),           # --text-muted
                "label": QColor("#888888"),         # --text-muted
                "caption": QColor("#666666"),       # --text-disabled
                "note": QColor("#666666")}          # --text-disabled
    return {"title": QColor("#334155"),             # text_secondary (light)
            "sub": QColor("#475569"),               # text_muted (light)
            "label": QColor("#475569"),             # text_muted (light)
            "caption": QColor("#64748b"),           # text_disabled (light)
            "note": QColor("#64748b")}              # text_disabled (light)


def sheet_input(invalid: bool, is_dark: bool) -> dict:
    """Text inputs (handoff §4.4): translucent fill, hairline border, blue
    focus border; an invalid field takes the error red for its border, and
    its message uses the same red."""
    if is_dark:
        d = {"bg": with_alpha("#ffffff", 0.04),
             "border": with_alpha("#ffffff", 0.10),
             "ink": QColor("#ffffff")}
    else:
        d = {"bg": QColor("#ffffff"),               # bg_input (light)
             "border": QColor("#cbd5e1"),           # border_light (light)
             "ink": QColor("#0f172a")}              # text_primary (light)
    d["focus_border"] = QColor("#3399ff")           # --blue-border
    d["error"] = QColor("#ff7575")                  # error
    if invalid:
        d["border"] = d["error"]
    return d


def frow(is_dark: bool) -> dict:
    """'Toon this account shows' row (handoff §4.4)."""
    if is_dark:
        return {"bg": QColor("#2e2e2e"),            # --bg-card-inner
                "border": QColor("#363636"),        # --border-card
                "name": QColor("#ffffff"),
                "sub": QColor("#888888"),           # --text-muted
                "portrait_bg": with_alpha("#000000", 0.22)}
    return {"bg": QColor("#f1f5f9"),                # bg_card_inner (light)
            "border": QColor("#e2e8f0"),            # border_card (light)
            "name": QColor("#0f172a"),              # text_primary (light)
            "sub": QColor("#475569"),               # text_muted (light)
            "portrait_bg": with_alpha("#0f172a", 0.06)}


def link_button(is_dark: bool) -> dict:
    """`.linkbtn` — Choose toon: a quiet hairline button."""
    if is_dark:
        return {"bg": with_alpha("#000000", 0.0),
                "border": QColor("#363636"),        # --border-card
                "ink": QColor("#bbbbbb")}           # --text-secondary
    return {"bg": with_alpha("#000000", 0.0),
            "border": QColor("#e2e8f0"),            # border_card (light)
            "ink": QColor("#334155")}               # text_secondary (light)


def danger_button(hover: bool, is_dark: bool) -> dict:
    """The remove button (handoff §4.4). The dark reds are tuned to glow on a
    dark sheet and fall to 3:1 on white, so light takes the darker step."""
    if is_dark:
        if hover:
            return {"bg": with_alpha("#e05252", 0.14),
                    "border": QColor("#e05252"),
                    "ink": QColor("#ff9b9b")}
        return {"bg": with_alpha("#000000", 0.0),
                "border": with_alpha("#e07878", 0.32),
                "ink": QColor("#e07878")}
    if hover:
        return {"bg": with_alpha("#e05252", 0.10),
                "border": QColor("#c62828"),
                "ink": QColor("#a31515")}
    return {"bg": with_alpha("#000000", 0.0),
            "border": with_alpha("#c62828", 0.38),
            "ink": QColor("#c62828")}


def sheet_chrome_button(hover: bool, is_dark: bool) -> dict:
    """The back arrow and the one `.sheet-x` cross-link (handoff §4.5)."""
    if is_dark:
        if hover:
            return {"bg": with_alpha("#ffffff", 0.09),
                    "border": QColor("#555555"),    # --border-light
                    "ink": QColor("#ffffff")}
        return {"bg": with_alpha("#ffffff", 0.05),
                "border": with_alpha("#ffffff", 0.13),
                "ink": QColor("#888888")}           # --text-muted
    if hover:
        return {"bg": with_alpha("#0f172a", 0.09),
                "border": QColor("#cbd5e1"),        # border_light (light)
                "ink": QColor("#0f172a")}           # text_primary (light)
    return {"bg": with_alpha("#0f172a", 0.05),
            "border": with_alpha("#0f172a", 0.13),
            "ink": QColor("#475569")}               # text_muted (light)


def sheet_footer_button(primary: bool, hover: bool, is_dark: bool) -> dict:
    """Cancel (quiet) and Save (--blue filled, --blue-border on hover)."""
    if primary:
        return {"bg": QColor("#3399ff") if hover else QColor("#0077ff"),
                "border": with_alpha("#000000", 0.0),
                "ink": QColor("#ffffff")}
    if is_dark:
        return {"bg": with_alpha("#000000", 0.0),
                "border": with_alpha("#ffffff", 0.15),
                "ink": QColor("#bbbbbb")}           # --text-secondary
    return {"bg": with_alpha("#000000", 0.0),
            "border": with_alpha("#0f172a", 0.15),
            "ink": QColor("#334155")}               # text_secondary (light)


def browser_empty_ink(is_dark: bool) -> dict:
    """The choose-a-toon empty state (handoff §4.7)."""
    if is_dark:
        return {"title": QColor("#ffffff"),
                "body": QColor("#888888")}          # --text-muted
    return {"title": QColor("#0f172a"),             # text_primary (light)
            "body": QColor("#475569")}              # text_muted (light)
