"""InlineNameEdit: label at rest, line edit while editing; commit/cancel rules."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from utils.widgets.keysets.inline_name_edit import InlineNameEdit


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _edit(app, text="New Set"):
    e = InlineNameEdit()
    e.set_text_quiet(text)
    e.show()
    got = {"committed": [], "cancelled": 0}
    e.committed.connect(got["committed"].append)
    e.cancelled.connect(lambda: got.__setitem__("cancelled", got["cancelled"] + 1))
    return e, got


def _focus_out(e):
    e.focusOutEvent(QFocusEvent(QEvent.FocusOut))


def test_rest_state_is_read_only_with_pointer_cursor(app):
    e, _ = _edit(app)
    assert e.isReadOnly() is True
    assert e.is_editing() is False
    assert e.cursor().shape() == Qt.PointingHandCursor
    assert e.toolTip() == "Click to rename"


def test_begin_edit_makes_editable_and_selects_all(app):
    e, _ = _edit(app)
    e.begin_edit()
    assert e.isReadOnly() is False
    assert e.is_editing() is True
    assert e.selectedText() == "New Set"


def test_enter_commits_trimmed_text(app):
    e, got = _edit(app)
    e.begin_edit()
    e.setText("  Arrows  ")
    QTest.keyClick(e, Qt.Key_Return)
    assert got["committed"] == ["Arrows"]
    assert e.text() == "Arrows"
    assert e.isReadOnly() is True and e.is_editing() is False


def test_empty_or_unchanged_text_is_a_cancel(app):
    for typed in ("   ", "New Set"):
        e, got = _edit(app)
        e.begin_edit()
        e.setText(typed)
        QTest.keyClick(e, Qt.Key_Return)
        assert got["committed"] == []
        assert got["cancelled"] == 1
        assert e.text() == "New Set"


def test_escape_reverts(app):
    e, got = _edit(app)
    e.begin_edit()
    e.setText("Arrows")
    QTest.keyClick(e, Qt.Key_Escape)
    assert e.text() == "New Set"
    assert got["committed"] == [] and got["cancelled"] == 1
    assert e.isReadOnly() is True


def test_focus_out_commits(app):
    e, got = _edit(app)
    e.begin_edit()
    e.setText("Arrows")
    _focus_out(e)
    assert got["committed"] == ["Arrows"]
    assert e.is_editing() is False


def test_locked_ignores_begin_edit_and_has_no_affordance(app):
    e, got = _edit(app, "Default")
    e.set_locked(True)
    e.begin_edit()
    assert e.is_editing() is False and e.isReadOnly() is True
    assert e.cursor().shape() == Qt.ArrowCursor
    assert e.toolTip() == ""


def test_locking_mid_edit_cancels_silently(app):
    e, got = _edit(app)
    e.begin_edit()
    e.setText("Arrows")
    e.set_locked(True)
    assert e.text() == "New Set"
    assert got["committed"] == [] and got["cancelled"] == 0


def test_set_text_quiet_mid_edit_drops_the_edit_without_signals(app):
    e, got = _edit(app)
    e.begin_edit()
    e.setText("Arrows")
    e.set_text_quiet("Other")
    assert e.text() == "Other"
    assert e.is_editing() is False
    assert got["committed"] == [] and got["cancelled"] == 0


def test_click_at_rest_enters_edit_mode(app):
    e, _ = _edit(app)
    QTest.mouseClick(e, Qt.LeftButton)
    assert e.is_editing() is True


def test_size_hint_tracks_text_width(app):
    e, _ = _edit(app, "Ab")
    short = e.sizeHint().width()
    e.set_text_quiet("A considerably longer set name")
    assert e.sizeHint().width() > short
    assert e.sizeHint().width() <= 320
