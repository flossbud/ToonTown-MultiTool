"""Accounts rows drag through the backend's per-game stable-ID reorder."""
import json
import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDrag, QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_accounts_sheet import Stage
from tests.test_launchpad_accounts import stage, isolated, add
from utils.widgets.launchpad.accounts_backend import FakeAccountsBackend

MIME = 'application/x-ttmt-account'


@pytest.fixture
def fake_stage(qapp):
    built = Stage(qapp)
    yield built
    built.close()


def drag_data(game, account_id):
    data = QMimeData()
    data.setData(MIME, json.dumps({'game': game, 'id': account_id}).encode())
    return data


def drop_on(row, game, account_id, *, before=True):
    point = QPoint(row.width() // 2, 2 if before else row.height() - 2)
    data = drag_data(game, account_id)
    enter = QDragEnterEvent(point, Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(row, enter)
    drop = QDropEvent(QPointF(point), Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(row, drop)
    QApplication.processEvents()  # sheet applies the move after native drag returns
    return enter.isAccepted(), drop.isAccepted()


@pytest.mark.parametrize('before,expected', [
    (True, ['t1', 't4', 't2', 't3', 't5']),
    (False, ['t1', 't2', 't4', 't3', 't5']),
])
def test_drop_reorders_within_game_without_opening_account(fake_stage, before, expected):
    sheet, backend = fake_stage.sheet, fake_stage.backend
    cc = backend.accounts('cc')
    assert drop_on(sheet.rows['t2'], 'ttr', 't4', before=before) == (True, True)
    assert [a.id for a in backend.accounts('ttr')] == expected
    assert backend.accounts('cc') == cc
    assert sheet.account_id() is None
    assert [r.account().id for r in sheet.cards['ttr'].rows() if hasattr(r, 'account')] == expected


def test_foreign_game_drag_is_rejected_without_backend_write(fake_stage):
    sheet, backend = fake_stage.sheet, fake_stage.backend
    before = backend.accounts('ttr')
    assert drop_on(sheet.rows['t2'], 'cc', 'c1') == (False, False)
    assert backend.accounts('ttr') == before
    assert backend.calls == []


def test_fake_backend_validates_membership_and_preserves_records():
    backend = FakeAccountsBackend.demo()
    before = backend.accounts('ttr')
    changed = []
    backend.changed.connect(lambda: changed.append(True))
    assert backend.reorder_accounts('ttr', ['t1', 't1']) is False
    assert backend.reorder_accounts('ttr', ['missing']) is False
    ordered = [a.id for a in reversed(before)]
    assert backend.reorder_accounts('ttr', ordered) is True
    assert backend.accounts('ttr') == list(reversed(before))
    assert changed == [True]


def test_stale_drag_and_self_drop_do_not_write(fake_stage):
    sheet, backend = fake_stage.sheet, fake_stage.backend
    before = backend.accounts('ttr')
    drop_on(sheet.rows['t2'], 'ttr', 'missing')
    drop_on(sheet.rows['t2'], 'ttr', 't2')
    assert backend.accounts('ttr') == before
    assert backend.calls == []


def test_drag_gesture_starts_native_move_and_does_not_open_account(fake_stage, monkeypatch):
    row = fake_stage.sheet.rows['t1']
    seen = []
    def execute(drag, action):
        seen.append((json.loads(bytes(drag.mimeData().data(MIME))), action))
        return Qt.IgnoreAction
    monkeypatch.setattr(QDrag, 'exec', execute)
    start, end = QPoint(100, 28), QPoint(140, 28)
    QTest.mousePress(row, Qt.LeftButton, Qt.NoModifier, start)
    QApplication.sendEvent(row, QMouseEvent(
        QEvent.MouseMove, QPointF(end), QPointF(row.mapToGlobal(end)),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QTest.mouseRelease(row, Qt.LeftButton, Qt.NoModifier, end)
    assert seen == [({'game': 'ttr', 'id': 't1'}, Qt.MoveAction)]
    assert fake_stage.sheet.account_id() is None


def test_real_backend_reorders_launcher_and_store_preserving_slots_and_other_game(stage):
    first = add(stage, 'ttr', 'first')
    other = add(stage, 'cc', 'clash')
    second = add(stage, 'ttr', 'second')
    tab = stage.launch_tab
    original = dict(tab._slots['ttr'])
    assert stage.accounts_backend.reorder_accounts('ttr', [second, first]) is True
    assert [a.id for a in tab._ordered_accounts('ttr')] == [second, first]
    assert [a.id for a in stage.accounts_backend.accounts('ttr')] == [second, first]
    assert [a.id for a in tab._ordered_accounts('cc')] == [other]
    assert all(tab._slots['ttr'][key] is slot for key, slot in original.items())
