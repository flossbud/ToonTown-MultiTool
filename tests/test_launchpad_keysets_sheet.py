"""Keysets sheet on a real KeymapManager (tmp config dir), mounted in the
sheet host under the app's real stylesheet."""
import json
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from utils import logical_actions, theme_manager
from utils.keymap_manager import KeymapManager
from utils.widgets.launchpad import keysets_sheet as ks
from utils.widgets.launchpad.keysets_sheet import KeysetsSheet, cap_text
from utils.widgets.launchpad.slide_sheet import SlideSheetHost


@contextmanager
def _theme(qapp, theme):
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    try:
        theme_manager.apply_theme(qapp, theme)
        yield
    finally:
        qapp.setStyleSheet(before_sheet)
        qapp.setPalette(before_palette)
        theme_manager._APPLIED_THEME = before_marker


@pytest.fixture
def reduced(monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)


@pytest.fixture
def km(tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return KeymapManager()


def _sheet(km, locked=False, is_dark=True, game="ttr"):
    return KeysetsSheet(km, is_dark=is_dark, game=game,
                        default_locked=lambda g: locked)


def _mounted(km, is_dark=True):
    win = QWidget()
    win.resize(880, 860)
    host = SlideSheetHost(win, is_dark=is_dark)
    sheet = _sheet(km, is_dark=is_dark)
    host.open(sheet, sheet.IDENTITY, sheet.TITLE, sheet.SUB)
    return win, host, sheet


def _flush(qapp):
    qapp.processEvents()
    QTest.qWait(1)


# ── structure ───────────────────────────────────────────────────────────────

def test_rows_follow_the_manager(qapp, km, reduced):
    km.add_set("ttr", keys={"forward": "w"})
    km.add_set("ttr")
    s = _sheet(km)
    assert [r.number for r in s.rows()] == [1, 2, 3]
    assert [r.set_id for r in s.rows()] == km.get_set_ids("ttr")
    assert [c.text() for c in s.rows()[1].caps][0] == "W"
    assert s.count_label.text() == "3 shown on strips · 3 of 8 used"


def test_count_line_mentions_hidden_only_when_there_are_some(qapp, km):
    sid = km.add_set("ttr")
    s = _sheet(km)
    km.set_hidden("ttr", sid, True)
    _flush(qapp)
    assert s.count_label.text() == "1 shown on strips · 1 hidden · 2 of 8 used"


def test_keyset_one_is_pinned(qapp, km):
    km.add_set("ttr")
    s = _sheet(km)
    one, two = s.rows()
    assert not one.delete_btn.isEnabled()
    assert one.grip._enabled is False
    assert two.delete_btn.isEnabled() and two.grip._enabled is True


def test_hide_disabled_on_last_visible_and_hidden_row_look(qapp, km):
    sid = km.add_set("ttr")
    s = _sheet(km)
    assert all(r.hide_btn.isEnabled() for r in s.rows())
    s.rows()[1].hide_btn.click()
    _flush(qapp)
    assert km.is_hidden("ttr", sid)
    one, two = s.rows()
    assert not one.hide_btn.isEnabled()          # last visible
    assert two.hide_btn.isEnabled()              # can be shown again
    assert two.status.text() == "Hidden from strips"
    assert two.frame.lit is False and one.frame.lit is True
    assert two.hide_btn.toolTip() == "Show on strips"


def test_base_set_can_be_hidden(qapp, km):
    km.add_set("ttr")
    s = _sheet(km)
    s.rows()[0].hide_btn.click()
    _flush(qapp)
    assert km.is_hidden("ttr", km.id_at("ttr", 0))


def test_add_and_limit(qapp, km):
    s = _sheet(km)
    for _ in range(7):
        assert s.add_button.isEnabled()
        s.add_button.click()
        _flush(qapp)
    assert km.num_sets("ttr") == 8
    assert not s.add_button.isEnabled()
    assert len(s.rows()) == 8


def test_delete_has_no_confirm_and_renumbers(qapp, km):
    a = km.add_set("ttr")
    b = km.add_set("ttr")
    s = _sheet(km)
    s.rows()[1].delete_btn.click()
    _flush(qapp)
    assert km.get_set_ids("ttr")[1:] == [b]
    assert [r.number for r in s.rows()] == [1, 2]
    assert s.rows()[1].set_id == b


def test_game_pill_switches_game(qapp, km):
    km.add_set("cc")
    s = _sheet(km)
    seen = []
    s.game_changed.connect(seen.append)
    s.set_game("cc")
    assert seen == ["cc"] and s.game() == "cc"
    assert [r.set_id for r in s.rows()] == km.get_set_ids("cc")
    assert s.game_pill.currentIndex() == 1


# ── editor ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("game", ["ttr", "cc"])
def test_editor_lists_every_action_of_the_game(qapp, km, game):
    s = _sheet(km, game=game)
    s.rows()[0].edit_btn.click()
    _flush(qapp)
    row = s.rows()[0]
    assert row.expanded and row.edit_btn._on
    assert list(row.edit_caps) == logical_actions.actions_for(game)


def test_open_editor_survives_renumbering(qapp, km):
    a = km.add_set("ttr")
    b = km.add_set("ttr")
    s = _sheet(km)
    s.expand_index(2)                      # b
    km.move_set("ttr", b, 1)
    _flush(qapp)
    assert s.rows()[1].set_id == b and s.rows()[1].expanded
    assert not s.rows()[2].expanded


def test_rebind_through_the_capture_field(qapp, km):
    sid = km.add_set("ttr")
    s = _sheet(km)
    s.expand_index(1)
    cap = s.rows()[1].edit_caps["jump"]
    cap.show()
    QTest.mouseClick(cap, Qt.LeftButton)
    assert cap._awaiting
    qapp.sendEvent(cap, QKeyEvent(QEvent.KeyPress, Qt.Key_X, Qt.NoModifier, "x"))
    _flush(qapp)
    assert km.get_set_by_id("ttr", sid)["jump"] == "x"
    assert s.rows()[1].expanded                       # still open after refresh
    assert s.rows()[1].edit_caps["jump"].text() == "X"


def test_locked_base_set_cannot_be_rebound(qapp, km):
    s = _sheet(km, locked=True)
    s.expand_index(0)
    cap = s.rows()[0].edit_caps["forward"]
    assert cap.is_locked()
    before = km.get_set("ttr", 0)["forward"]
    QTest.mouseClick(cap, Qt.LeftButton)
    qapp.sendEvent(cap, QKeyEvent(QEvent.KeyPress, Qt.Key_X, Qt.NoModifier, "x"))
    assert km.get_set("ttr", 0)["forward"] == before


def test_in_set_conflict_marks_caps_and_shows_banner(qapp, km):
    sid = km.add_set("ttr", keys={"forward": "w", "jump": "w"})
    s = _sheet(km)
    s.expand_index(1)
    row = s.rows()[1]
    assert "w" in row._conflicts
    assert row.conflict_banner.isVisibleTo(row)
    assert "rgba(224, 82, 82, 255)" in row.caps[0].styleSheet()      # Forward cap
    assert "rgba(224, 82, 82, 255)" in row.edit_caps["jump"].styleSheet()
    assert "rgba(224, 82, 82, 255)" not in row.caps[1].styleSheet()  # Left cap


def test_cross_set_conflict_is_listed(qapp, km):
    km.add_set("ttr", keys={"forward": "w"})
    km.add_set("ttr", keys={"gags": "w"})
    s = _sheet(km)
    s.expand_index(1)
    row = s.rows()[1]
    assert "w" in row._warn
    assert row.cross_label.isVisibleTo(row)
    assert "W is Forward here and Gags in keyset 3." in row.cross_label.text()


# ── drag to renumber ────────────────────────────────────────────────────────

def test_drag_renumbers_through_move_set(qapp, km, reduced):
    a = km.add_set("ttr")
    b = km.add_set("ttr")
    c = km.add_set("ttr")
    win, host, s = _mounted(km)
    win.show()
    _flush(qapp)
    rows = s.rows()
    grip = rows[1].grip                                      # a, keyset 2
    start = grip.mapToGlobal(grip.rect().center())
    below_last = rows[3].mapToGlobal(QPoint(10, rows[3].height() - 2))
    s._drag_start(a, start)
    s._drag_move(below_last)
    assert s._drag["to"] == 3
    assert s.drop_line.isVisible()
    s._drag_end(below_last)
    _flush(qapp)
    assert km.get_set_ids("ttr")[1:] == [b, c, a]
    assert not s.drop_line.isVisible()
    win.close()


def test_drag_never_reaches_index_zero(qapp, km, reduced):
    a = km.add_set("ttr")
    b = km.add_set("ttr")
    win, host, s = _mounted(km)
    win.show()
    _flush(qapp)
    top = s.rows()[0].mapToGlobal(QPoint(5, 1))
    s._drag_start(b, s.rows()[2].grip.mapToGlobal(QPoint(3, 3)))
    s._drag_move(top)
    assert s._drag["to"] == 1
    s._drag_end(top)
    _flush(qapp)
    assert km.get_set_ids("ttr")[1:] == [b, a]
    win.close()


def test_base_set_drag_is_ignored(qapp, km, reduced):
    km.add_set("ttr")
    s = _sheet(km)
    s._drag_start(km.id_at("ttr", 0), QPoint(0, 0))
    assert s._drag is None


# ── mounted render, both themes ─────────────────────────────────────────────

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_mounted_render(qapp, km, reduced, theme):
    km.add_set("ttr", keys={"forward": "w"})
    hid = km.add_set("ttr")
    km.set_hidden("ttr", hid, True)
    with _theme(qapp, theme):
        is_dark = theme == "dark"
        win, host, s = _mounted(km, is_dark=is_dark)
        s.expand_index(1)
        win.show()
        _flush(qapp)
        img = win.grab().toImage()
        # Number block of keyset 1 is drawn in the movement colour.
        r0 = s.rows()[0]
        centre = r0.frame.slot.mapTo(win, r0.frame.slot.rect().center())
        found = False
        for dx in range(-9, 10):
            col = img.pixelColor(centre.x() + dx, centre.y() - 9)
            if abs(col.red() - 0x4A) < 40 and abs(col.blue() - 0xE7) < 40:
                found = True
        assert found, "keyset 1's block is not painted"
        # The row's caps carry the keycap stylesheet, not the app's.
        assert "JetBrains Mono" in r0.caps[0].styleSheet()
        assert r0.caps[0].fontInfo().pixelSize() == 10
        win.close()


def test_keymap_callback_after_sheet_deleted_is_harmless(qapp, km):
    s = _sheet(km)
    s.deleteLater()
    _flush(qapp)
    QTest.qWait(5)
    km.add_set("ttr")             # must not raise


def test_cap_text():
    assert cap_text("w") == "W"
    assert cap_text("Up") == "↑"
    assert cap_text("Control_R") == "R Ctrl"
    assert cap_text("") == "–"
    assert cap_text(None) == "–"


# ── Detect from game (keyset 1) ─────────────────────────────────────────────

def test_detect_button_only_on_keyset_one(qapp, km):
    km.add_set("ttr")
    s = _sheet(km)
    s.expand_index(0)
    s.expand_index(1)
    one, two = s.rows()
    assert one.detect_btn is not None and one.detect_btn.text() == "Detect from game"
    assert two.detect_btn is None


@pytest.mark.parametrize("locked", [False, True])
def test_detect_uses_the_page_helper_and_relocks(qapp, km, monkeypatch, locked):
    calls, lock_checks = [], []
    sm = object()

    def fake_detect(game, keymap_manager, settings_manager):
        calls.append((game, keymap_manager, settings_manager))
        keymap_manager.update_set_key(game, 0, "forward", "i")
        return 1

    monkeypatch.setattr(ks.detect, "detect_settings_for_game", fake_detect)
    state = {"locked": locked}

    def lock_rule(game):
        lock_checks.append(game)
        return state["locked"]

    s = KeysetsSheet(km, settings_manager=sm, is_dark=True, default_locked=lock_rule)
    s.expand_index(0)
    assert s.rows()[0].detect_btn.isEnabled()        # available locked or not
    state["locked"] = True                           # a settings file appears
    before = len(lock_checks)
    s.rows()[0].detect_btn.click()
    _flush(qapp)
    assert calls == [("ttr", km, sm)]
    assert km.get_set("ttr", 0)["forward"] == "i"
    assert len(lock_checks) > before                 # lock rule re-read
    row = s.rows()[0]
    assert row.locked and row.expanded
    assert row.detect_label.text() == "Updated 1 key from TTR's settings."


def test_detect_with_nothing_found_says_so(qapp, km, monkeypatch):
    monkeypatch.setattr(ks.detect, "detect_settings_for_game", lambda g, k, s: 0)
    s = _sheet(km, game="cc")
    s.expand_index(0)
    s.rows()[0].detect_btn.click()
    _flush(qapp)
    assert s.rows()[0].detect_label.text() == "No changes found in CC's settings."
    s.set_game("ttr")
    s.expand_index(0)
    assert not s.rows()[0].detect_label.isVisibleTo(s.rows()[0])


def test_sheet_does_not_load_the_old_keysets_page():
    """The sheet survives the Settings Keysets page: importing it must not
    pull in the old page's modules (they are deleted at cut-over)."""
    import subprocess
    import sys
    code = ("import sys; import utils.widgets.launchpad.keysets_sheet; "
            "old = ['keysets_page', 'split_editor', 'game_picker', 'inline_name_edit', "
            "'set_list', 'visual_keyboard', 'keyboard_data']; "
            "print([m for m in old if 'utils.widgets.keysets.' + m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


def test_rules_are_shared_with_the_old_page():
    from utils.widgets.keysets import keysets_page, rules, split_editor
    assert keysets_page.default_set_locked is rules.default_set_locked
    assert split_editor._CONFLICT_TEXT == rules.CONFLICT_TEXT
