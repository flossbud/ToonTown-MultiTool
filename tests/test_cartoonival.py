"""Cartoonival window and the token-visibility rule."""

import datetime as dt

import pytest

from utils.cartoonival import is_cartoonival, show_tokens


@pytest.mark.parametrize("year", [2025, 2026, 2028])
@pytest.mark.parametrize("month,day,want", [
    (9, 18, False),     # day before
    (9, 19, True),      # first day
    (10, 1, True),
    (10, 20, True),     # last day
    (10, 21, False),    # day after
    (1, 1, False),
    (12, 31, False),
])
def test_is_cartoonival_boundaries(year, month, day, want):
    assert is_cartoonival(dt.date(year, month, day)) is want


def test_datetime_uses_its_date():
    assert is_cartoonival(dt.datetime(2026, 9, 19, 0, 0, 1))
    assert is_cartoonival(dt.datetime(2026, 10, 20, 23, 59, 59))
    assert not is_cartoonival(dt.datetime(2026, 10, 21, 0, 0, 0))


def test_aware_datetime_is_judged_in_local_time():
    aware = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    local = aware.astimezone().date()
    assert is_cartoonival(aware) is is_cartoonival(local)


def test_default_is_today(monkeypatch):
    import utils.cartoonival as mod
    monkeypatch.setattr(mod, "_today", lambda: dt.date(2026, 9, 19))
    assert is_cartoonival()
    monkeypatch.setattr(mod, "_today", lambda: dt.date(2026, 9, 18))
    assert not is_cartoonival()


@pytest.mark.parametrize("game,day,tokens,want", [
    ("ttr", dt.date(2026, 9, 19), 12, True),
    ("ttr", dt.date(2026, 10, 20), 0, True),       # zero is a real value
    ("ttr", dt.date(2026, 9, 18), 12, False),      # just before
    ("ttr", dt.date(2026, 10, 21), 12, False),     # just after
    ("ttr", dt.date(2026, 10, 1), None, False),    # API gave no value
    ("cc", dt.date(2026, 10, 1), 12, False),       # not TTR
    ("", dt.date(2026, 10, 1), 12, False),
])
def test_show_tokens(game, day, tokens, want):
    assert show_tokens(game, day, tokens) is want
