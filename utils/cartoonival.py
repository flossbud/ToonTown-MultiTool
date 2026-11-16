"""Cartoonival: when TTR's event tokens are worth showing.

The event runs from September 19 to October 20 inclusive, every year, judged
on the user's local calendar date. Pure functions, no Qt and no clock reads
unless the caller leaves the date out.
"""

from __future__ import annotations

import datetime as _dt

START = (9, 19)    # (month, day), inclusive
END = (10, 20)     # (month, day), inclusive


def _today() -> _dt.date:
    return _dt.date.today()


def _local_date(when) -> _dt.date:
    if when is None:
        return _today()
    if isinstance(when, _dt.datetime):
        # An aware datetime is converted to local time first; a naive one is
        # taken as already local.
        if when.tzinfo is not None:
            when = when.astimezone()
        return when.date()
    return when


def is_cartoonival(when: _dt.date | _dt.datetime | None = None) -> bool:
    """True from Sep 19 to Oct 20 inclusive (local date), any year."""
    d = _local_date(when)
    return START <= (d.month, d.day) <= END


def show_tokens(game: str, when: _dt.date | _dt.datetime | None, tokens) -> bool:
    """Whether a toon's token count belongs on screen: TTR only, during
    Cartoonival, and only when the game API reported a value."""
    return game == "ttr" and tokens is not None and is_cartoonival(when)
