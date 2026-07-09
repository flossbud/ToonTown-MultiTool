import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.logs_console.model import LINE_ROLE, LogLineModel
from utils.widgets.logs_console.proxy import LogFilterProxy
from utils.widgets.logs_console.records import make_line


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def stack(qapp):
    m = LogLineModel()
    p = LogFilterProxy()
    p.setSourceModel(m)
    now = datetime(2026, 7, 9, 12, 0, 0)
    for msg in ("[Credentials] Keyring ready",
                "[Service] Input service started",
                "[TTR API] Login OK",
                "plain raw line"):
        m.append(make_line(msg, now=now))
    return m, p


def _messages(p):
    return [p.index(i, 0).data(LINE_ROLE).message for i in range(p.rowCount())]


def test_default_shows_all(stack):
    _, p = stack
    assert p.rowCount() == 4


def test_scope_filters_by_source(stack):
    _, p = stack
    p.set_scope("input")
    assert _messages(p) == ["Input service started"]
    p.set_scope("raw")
    assert _messages(p) == ["Keyring ready", "plain raw line"]


def test_tag_filter_multiselect(stack):
    _, p = stack
    p.set_active_tags({"[Credentials]", "[TTR API]"})
    assert p.rowCount() == 2


def test_empty_tag_set_means_no_tag_filtering(stack):
    _, p = stack
    p.set_active_tags(set())
    assert p.rowCount() == 4


def test_query_case_insensitive_over_tag_and_message(stack):
    _, p = stack
    p.set_query("keyring")
    assert p.rowCount() == 1
    p.set_query("credentials")          # matches the TAG text
    assert p.rowCount() == 1
    p.set_query("zzz")
    assert p.rowCount() == 0


def test_filters_compose(stack):
    _, p = stack
    p.set_scope("raw")
    p.set_active_tags({"[Credentials]"})
    p.set_query("ready")
    assert _messages(p) == ["Keyring ready"]


def test_live_append_respects_active_filter(stack):
    m, p = stack
    p.set_scope("input")
    assert p.rowCount() == 1
    m.append(make_line("[Service] second input line"))
    m.append(make_line("plain raw tail"))   # excluded by scope
    assert _messages(p) == ["Input service started", "second input line"]


def test_query_is_stripped(stack):
    _, p = stack
    p.set_query("  keyring  ")
    assert p.rowCount() == 1
