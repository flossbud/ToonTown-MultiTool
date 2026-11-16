"""The account sheet's pure rules: validation, the rename merge, the shown
record — and the colour-escape scan for every grandstand widget module."""
import glob
import os
import re
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.widgets.grandstand.draft import (
    MODE_ADD, MODE_EDIT, PASSWORD_REQUIRED, USERNAME_REQUIRED, AccountDraft,
    shown_record, unique_toons,
)


def _draft(mode=MODE_EDIT, **kw):
    base = dict(id="a" if mode == MODE_EDIT else "", game="ttr", mode=mode,
                label="Gag alt", username="flossbud", password="pw",
                keyring_has_password=True, keyring_readable=True)
    base.update(kw)
    return AccountDraft(**base)


def _rec(name, dna, game="ttr"):
    return SimpleNamespace(toon_name=name, dna=dna, game=game, species="cat",
                           accent=None, laff=None, max_laff=None)


# ── validation (spec §4) ────────────────────────────────────────────────────

def test_messages_are_the_handoff_copy():
    assert USERNAME_REQUIRED == "Username is required"
    assert PASSWORD_REQUIRED == "Password is required"


def test_add_mode_requires_username_and_password():
    errors = _draft(MODE_ADD, username="", password="").validate()
    assert errors == {"username": USERNAME_REQUIRED,
                      "password": PASSWORD_REQUIRED}


def test_whitespace_is_not_a_value():
    errors = _draft(MODE_ADD, username="   ", password="\t").validate()
    assert set(errors) == {"username", "password"}


def test_edit_with_a_stored_password_accepts_a_blank_one():
    """A label change never demands retyping a password the keyring holds:
    blank means 'keep the current one' (today's update_account(password=None))."""
    assert _draft(password="", keyring_has_password=True).validate() == {}


def test_edit_without_a_stored_password_requires_one():
    errors = _draft(password="", keyring_has_password=False).validate()
    assert errors == {"password": PASSWORD_REQUIRED}


def test_edit_with_an_unreadable_keyring_never_requires_a_password():
    """Keyring unavailable: the field is empty and keyring_has_password is
    False, yet Save must still work — a blank keeps whatever is stored."""
    d = _draft(password="", keyring_has_password=False, keyring_readable=False)
    assert d.validate() == {}
    assert d.password_required() is False


def test_add_mode_requires_a_password_even_when_the_keyring_is_unreadable():
    d = _draft(MODE_ADD, password="", keyring_readable=False)
    assert d.validate() == {"password": PASSWORD_REQUIRED}


def test_username_is_always_required():
    assert _draft(username="").validate() == {"username": USERNAME_REQUIRED}


def test_a_whitespace_password_means_keep_the_stored_one():
    """validate() strips, so "   " passes it. The save site must not then
    write those spaces over a good keyring entry: only password_for_save()
    decides what is written, and blank-after-strip means keep."""
    assert _draft(password="   ").password_for_save() is None
    assert _draft(password="").password_for_save() is None
    assert _draft(password="\t\n ").password_for_save() is None
    assert _draft(password="pw").password_for_save() == "pw"


def test_a_password_with_edge_spaces_is_written_exactly_as_typed():
    """Whitespace-only still means "keep", but a password that has real
    characters is nobody's business to trim: Add writes the raw string
    (cred_manager.add_account(password=draft.password)), so a stripped Edit
    would silently corrupt an account that logs in today."""
    assert _draft(password="  pw  ").password_for_save() == "  pw  "
    assert _draft(password=" pw").password_for_save() == " pw"
    assert _draft(password="pw ").password_for_save() == "pw "


def test_display_name_prefers_the_label():
    assert _draft().display_name == "Gag alt"
    assert _draft(label="").display_name == "flossbud"
    assert _draft(label="", username="").display_name == ""


# ── rename ghosts (spec §3) ─────────────────────────────────────────────────

def test_identical_dna_collapses_to_the_newest_name():
    """Katsuro is Blue Cat renamed: one toon, the store's newest record wins."""
    merged = unique_toons([_rec("Katsuro", "7400"), _rec("Blue Cat", "7400"),
                           _rec("Pepper", "7401")])
    assert [r.toon_name for r in merged] == ["Katsuro", "Pepper"]


def test_cc_records_with_an_empty_dna_never_merge():
    merged = unique_toons([_rec("Hiro", "", "cc"), _rec("Bonzo", "", "cc")])
    assert [r.toon_name for r in merged] == ["Hiro", "Bonzo"]


def test_merge_keeps_store_order_and_the_input_untouched():
    records = [_rec("A", "1"), _rec("B", "2"), _rec("C", "1")]
    merged = unique_toons(records)
    assert [r.toon_name for r in merged] == ["A", "B"]
    assert len(records) == 3


# ── the record an account shows ─────────────────────────────────────────────

def test_shown_record_is_the_primary_when_known_else_the_newest():
    records = [_rec("Pepper", "7401"), _rec("Flossbud", "7400")]
    assert shown_record(records, "Flossbud").toon_name == "Flossbud"
    assert shown_record(records, None).toon_name == "Pepper"
    assert shown_record(records, "Gone").toon_name == "Pepper"
    assert shown_record([], "Flossbud") is None


# ── discipline ──────────────────────────────────────────────────────────────

_LITERAL = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|rgba\(")


def test_no_colour_literals_outside_the_palette():
    """Every colour goes through palette.py. The regex needs a word boundary
    so an object-name selector like `#gs_sheet` or `#account_sheet` is not
    mistaken for hex."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "utils", "widgets", "grandstand")
    offenders = []
    for path in sorted(glob.glob(os.path.join(root, "*.py"))):
        if os.path.basename(path) == "palette.py":
            continue
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                if _LITERAL.search(line):
                    offenders.append(f"{os.path.basename(path)}:{number}: {line.strip()}")
    assert offenders == []


# ── sheet tokens (handoff §4.4, §4.5, §9) ───────────────────────────────────

from PySide6.QtGui import QColor                    # noqa: E402
from utils.color_math import with_alpha             # noqa: E402
from utils.widgets.grandstand import palette as gp  # noqa: E402


def test_sheet_surface_is_the_card_panel():
    d = gp.sheet_surface(True)
    assert d["bg"] == QColor("#252525")              # --bg-card
    assert d["border"] == QColor("#363636")          # --border-card


def test_sheet_ink_dark_tokens():
    d = gp.sheet_ink(True)
    assert d["title"] == QColor("#bbbbbb")           # --text-secondary
    assert d["sub"] == d["label"] == QColor("#888888")   # --text-muted
    assert d["caption"] == d["note"] == QColor("#666666")  # --text-disabled


def test_sheet_input_dark_tokens_and_the_invalid_border():
    ok = gp.sheet_input(False, True)
    assert ok["bg"] == with_alpha("#ffffff", 0.04)
    assert ok["border"] == with_alpha("#ffffff", 0.10)
    assert ok["focus_border"] == QColor("#3399ff")   # --blue-border
    assert ok["error"] == QColor("#ff7575")
    bad = gp.sheet_input(True, True)
    assert bad["border"] == QColor("#ff7575")
    assert bad["ink"] == ok["ink"] == QColor("#ffffff")


def test_frow_tokens():
    d = gp.frow(True)
    assert d["bg"] == QColor("#2e2e2e")              # --bg-card-inner
    assert d["border"] == QColor("#363636")          # --border-card
    assert d["name"] == QColor("#ffffff")
    assert d["sub"] == QColor("#888888")             # --text-muted


def test_link_button_tokens():
    d = gp.link_button(True)
    assert d["border"] == QColor("#363636")          # --border-card
    assert d["ink"] == QColor("#bbbbbb")             # --text-secondary
    assert d["bg"].alpha() == 0


def test_danger_button_rest_and_hover():
    rest = gp.danger_button(False, True)
    assert rest["ink"] == QColor("#e07878")
    assert rest["border"] == with_alpha("#e07878", 0.32)
    hover = gp.danger_button(True, True)
    assert hover["bg"] == with_alpha("#e05252", 0.14)
    assert hover["border"] == QColor("#e05252")
    assert hover["ink"] == QColor("#ff9b9b")


def test_danger_button_light_reds_hold_contrast_on_the_white_sheet():
    """The dark reds measure about 3:1 on #ffffff; light takes darker steps."""
    rest = gp.danger_button(False, False)
    assert rest["ink"] == QColor("#c62828")
    assert rest["border"] == with_alpha("#c62828", 0.38)
    hover = gp.danger_button(True, False)
    assert hover["ink"] == QColor("#a31515")
    assert hover["border"] == QColor("#c62828")


def test_sheet_chrome_button_rest_and_hover():
    """`.sheet-x` and the back arrow (handoff §4.5)."""
    rest = gp.sheet_chrome_button(False, True)
    assert rest["bg"] == with_alpha("#ffffff", 0.05)
    assert rest["border"] == with_alpha("#ffffff", 0.13)
    assert rest["ink"] == QColor("#888888")          # --text-muted
    hover = gp.sheet_chrome_button(True, True)
    assert hover["bg"] == with_alpha("#ffffff", 0.09)
    assert hover["border"] == QColor("#555555")      # --border-light
    assert hover["ink"] == QColor("#ffffff")


def test_save_is_blue_filled_and_hovers_to_blue_border():
    save = gp.sheet_footer_button(True, False, True)
    assert save["bg"] == QColor("#0077ff")           # --blue
    assert save["ink"] == QColor("#ffffff")
    assert gp.sheet_footer_button(True, True, True)["bg"] == QColor("#3399ff")
    cancel = gp.sheet_footer_button(False, False, True)
    assert cancel["bg"].alpha() == 0
    assert cancel["ink"] == QColor("#bbbbbb")        # --text-secondary


def test_browser_empty_ink():
    d = gp.browser_empty_ink(True)
    assert d["title"] == QColor("#ffffff")
    assert d["body"] == QColor("#888888")            # --text-muted


# Every sheet token, with the keys whose light branch must NOT be the dark
# one. One token is deliberately theme-independent and is listed apart: the
# blue Save fill.
THEMED_SHEET_TOKENS = (
    (gp.sheet_surface, (), ("bg", "border")),
    (gp.sheet_ink, (), ("title", "sub")),
    (gp.sheet_input, (False,), ("bg", "border")),
    (gp.frow, (), ("bg", "border")),
    (gp.link_button, (), ("border", "ink")),
    (gp.sheet_chrome_button, (False,), ("bg", "border")),
    (gp.sheet_footer_button, (False, False), ("border", "ink")),
    (gp.browser_empty_ink, (), ("title", "body")),
    (gp.danger_button, (False,), ("border", "ink")),
    (gp.danger_button, (True,), ("border", "ink")),
)
UNTHEMED_SHEET_TOKENS = (
    (gp.sheet_footer_button, (True, False)),
    (gp.sheet_footer_button, (True, True)),
)


def test_every_sheet_token_accepts_both_themes():
    """Both branches must return real colours for every key — and the light
    branch must actually be a light branch. `is not None` would pass on a
    light theme that simply returned the dark dict."""
    for fn, args, differing in THEMED_SHEET_TOKENS:
        dark, light = fn(*args, True), fn(*args, False)
        assert set(dark) == set(light), fn.__name__
        for key, colour in list(dark.items()) + list(light.items()):
            assert colour.isValid(), f"{fn.__name__}[{key}]"
        for key in differing:
            assert dark[key] != light[key], f"{fn.__name__}[{key}] is theme-blind"


def test_the_theme_independent_sheet_tokens_are_deliberate():
    """Danger red and the blue Save fill are the same in both themes."""
    for fn, args in UNTHEMED_SHEET_TOKENS:
        assert fn(*args, True) == fn(*args, False), fn.__name__


def test_sheet_tokens_have_a_light_branch():
    """Light values are theme_manager's light tokens of the same name."""
    assert gp.sheet_surface(False) == {"bg": QColor("#ffffff"),
                                       "border": QColor("#e2e8f0")}
    assert gp.sheet_ink(False)["title"] == QColor("#334155")     # text_secondary
    assert gp.sheet_ink(False)["sub"] == QColor("#475569")       # text_muted
    assert gp.sheet_ink(False)["caption"] == QColor("#64748b")   # text_disabled
    light_input = gp.sheet_input(False, False)
    assert light_input["ink"] == QColor("#0f172a")               # text_primary
    assert light_input["border"] == QColor("#cbd5e1")            # border_light
    assert light_input["bg"] == QColor("#ffffff")                # bg_input
    assert gp.sheet_input(True, False)["border"] == QColor("#ff7575")
    assert gp.frow(False)["bg"] == QColor("#f1f5f9")             # bg_card_inner
    assert gp.frow(False)["name"] == QColor("#0f172a")
    assert gp.link_button(False)["ink"] == QColor("#334155")
    assert gp.sheet_chrome_button(True, False)["ink"] == QColor("#0f172a")
    assert gp.sheet_footer_button(False, False, False)["ink"] == QColor("#334155")
    assert gp.browser_empty_ink(False) == {"title": QColor("#0f172a"),
                                           "body": QColor("#475569")}
    # Save's blue is theme-independent.
    assert gp.sheet_footer_button(True, False, False) == gp.sheet_footer_button(True, False, True)
    # And the light branch is a different surface, not the dark one renamed.
    assert gp.sheet_surface(False)["bg"] != gp.sheet_surface(True)["bg"]
    assert gp.sheet_ink(False)["title"] != gp.sheet_ink(True)["title"]
