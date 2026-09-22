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
