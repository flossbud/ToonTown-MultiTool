import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.logs_console.model import BUFFER_CAP, LINE_ROLE, LogLineModel
from utils.widgets.logs_console.records import make_line


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _line(msg, **kw):
    return make_line(msg, now=datetime(2026, 7, 9, 12, 0, 0), **kw)


def test_append_grows_and_data_roles(qapp):
    m = LogLineModel()
    m.append(_line("[Credentials] Keyring ready"))
    assert m.rowCount() == 1
    line = m.index(0, 0).data(LINE_ROLE)
    assert line.tag == "[Credentials]"
    assert m.index(0, 0).data() == "[12:00:00] [Credentials] Keyring ready"


def test_ring_cap_drops_oldest(qapp):
    m = LogLineModel()
    for i in range(BUFFER_CAP + 25):
        m.append(_line(f"line {i}"))
    assert m.rowCount() == BUFFER_CAP
    assert m.index(0, 0).data(LINE_ROLE).message == "line 25"


def test_append_at_cap_emits_remove_then_insert(qapp):
    m = LogLineModel()
    for i in range(BUFFER_CAP):
        m.append(_line(f"line {i}"))
    events = []
    m.rowsRemoved.connect(
        lambda parent, first, last: events.append(("removed", first, last)))
    m.rowsInserted.connect(
        lambda parent, first, last: events.append(("inserted", first, last)))
    m.append(_line("overflowing line"))
    assert events == [
        ("removed", 0, 0),
        ("inserted", BUFFER_CAP - 1, BUFFER_CAP - 1),
    ]
    assert m.rowCount() == BUFFER_CAP


def test_append_below_cap_emits_insert_only(qapp):
    m = LogLineModel()
    events = []
    m.rowsRemoved.connect(
        lambda parent, first, last: events.append(("removed", first, last)))
    m.rowsInserted.connect(
        lambda parent, first, last: events.append(("inserted", first, last)))
    m.append(_line("a"))
    assert events == [("inserted", 0, 0)]


def test_clear_scope_single_source(qapp):
    m = LogLineModel()
    m.append(_line("[Service] input line"))       # input
    m.append(_line("[TTR API] api line"))         # api
    m.append(_line("raw line"))                   # raw
    m.clear_scope("raw")
    assert [m.index(i, 0).data(LINE_ROLE).source for i in range(m.rowCount())] \
        == ["input", "api"]


def test_clear_scope_all(qapp):
    m = LogLineModel()
    m.append(_line("[Service] x"))
    m.append(_line("y"))
    m.clear_scope(None)
    assert m.rowCount() == 0


def test_lines_accessor_is_snapshot(qapp):
    m = LogLineModel()
    m.append(_line("a"))
    snap = m.lines()
    m.append(_line("b"))
    assert len(snap) == 1 and len(m.lines()) == 2
