"""CredentialsManager.reorder_game reorders one game's accounts in place."""
import pytest
from tests.test_credentials_manager_cc_tokens import cm  # reuse the tmp-keyring fixture


def _ids(cm, game=None):
    return [a.id for a in cm.get_accounts_metadata(game)]


def test_reorder_game_reorders_within_game(cm):
    for i in range(3):
        cm.add_account(label=f"T{i}", username=f"u{i}", password="", game="ttr")
    ids = _ids(cm, "ttr")
    new = [ids[2], ids[0], ids[1]]
    assert cm.reorder_game("ttr", new) is True
    assert _ids(cm, "ttr") == new


def test_reorder_preserves_other_games_order(cm):
    cm.add_account(label="T0", username="t0", password="", game="ttr")
    cm.add_account(label="C0", username="c0", password="", game="cc")
    cm.add_account(label="T1", username="t1", password="", game="ttr")
    cm.add_account(label="C1", username="c1", password="", game="cc")
    cc_before = _ids(cm, "cc")
    ttr = _ids(cm, "ttr")
    assert cm.reorder_game("ttr", [ttr[1], ttr[0]]) is True
    assert _ids(cm, "ttr") == [ttr[1], ttr[0]]
    assert _ids(cm, "cc") == cc_before  # CC order untouched


def test_reorder_rejects_mismatched_id_set(cm):
    cm.add_account(label="T0", username="u0", password="", game="ttr")
    cm.add_account(label="T1", username="u1", password="", game="ttr")
    ids = _ids(cm, "ttr")
    assert cm.reorder_game("ttr", [ids[0]]) is False              # missing one
    assert cm.reorder_game("ttr", ids + ["bogus"]) is False        # extra/foreign
    assert cm.reorder_game("ttr", [ids[0], ids[0]]) is False       # duplicate
    assert _ids(cm, "ttr") == ids                                  # unchanged on reject


def test_reorder_persists_and_emits(cm, monkeypatch):
    cm.add_account(label="T0", username="u0", password="", game="ttr")
    cm.add_account(label="T1", username="u1", password="", game="ttr")
    ids = _ids(cm, "ttr")
    saved, emitted = [], []
    monkeypatch.setattr(cm, "_save", lambda: saved.append(1))
    monkeypatch.setattr(cm, "_emit_change", lambda: emitted.append(1))
    assert cm.reorder_game("ttr", [ids[1], ids[0]]) is True
    assert saved == [1] and emitted == [1]


def test_reorder_same_order_is_noop_returns_true(cm):
    cm.add_account(label="T0", username="u0", password="", game="ttr")
    cm.add_account(label="T1", username="u1", password="", game="ttr")
    ids = _ids(cm, "ttr")
    assert cm.reorder_game("ttr", list(ids)) is True  # identical order: accepted no-op
    assert _ids(cm, "ttr") == ids


def test_reorder_skips_legacy_entry_without_id(cm):
    cm.add_account(label="T0", username="u0", password="", game="ttr")
    cm.add_account(label="T1", username="u1", password="", game="ttr")
    ids = _ids(cm, "ttr")
    cm._accounts.append({"label": "legacy", "username": "x", "game": "ttr"})  # no "id"
    # reorder of the real two must not KeyError on the id-less legacy entry.
    assert cm.reorder_game("ttr", [ids[1], ids[0]]) is True
