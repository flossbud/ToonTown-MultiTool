"""Missing Appearance contract cases reconciled with the wired Accounts router."""
import pytest
from tests.test_grandstand_appearance_flow import roster, _look, _records, _account
from tests.test_grandstand_appearance_sheet import host, _mount, _draft, _three, _rec, _land_poses, DNA
from tests.test_launchpad_accounts import stage, isolated, _two_toons
from utils.widgets.grandstand.appearance_draft import POSE_NAMES
from utils.widgets.launchpad.header import SHEET_ACCOUNTS


def switch_to(view, toon):
    editor = view.appearance_sheet
    editor.pill.click()
    editor.switcher.row_for(toon).click()


def answer_retarget(view):
    view.subject_toon_chosen.connect(lambda game, aid, toon: view.open_appearance_sheet(
        game, _look(aid, toon), _records(), 'Flossbud'))


def test_save_after_retarget_uses_only_the_toon_on_screen(roster):
    roster.set_accounts_elsewhere(True)
    answer_retarget(roster)
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    editor = roster.appearance_sheet
    editor.looks.swatches[5].click()
    switch_to(roster, 'Pepper')
    assert not editor.draft().is_dirty()
    editor.looks.swatches[2].click()
    saved = []
    roster.appearance_save_requested.connect(lambda game, draft: saved.append(draft))
    roster.sheet.save_button.click()
    assert len(saved) == 1
    assert saved[0].store_key == 'ttr::Pepper'
    assert saved[0].matching_look() == 2


def test_unanswered_retarget_preserves_the_current_unsaved_draft(roster):
    roster.set_accounts_elsewhere(True)
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    editor = roster.appearance_sheet
    editor.looks.swatches[5].click()
    switch_to(roster, 'Pepper')
    assert editor.draft().toon_name == 'Flossbud'
    assert editor.looks.selected() == 5
    saved = []
    roster.appearance_save_requested.connect(lambda game, draft: saved.append(draft.store_key))
    roster.sheet.save_button.click()
    assert saved == ['ttr::Flossbud']


def test_late_render_for_toon_left_behind_does_not_reach_editor(host, render_cache):
    facade, store, _ = render_cache
    pepper = _rec('Pepper Fizzlebounce', '7401', 'cat', laff=62)
    editor = _mount(host, _draft(), _three(), 'Flossbud')
    editor.open(_draft(rec=pepper), _three(), 'Flossbud')
    _land_poses(store, 'ttr', 'Flossbud', DNA)
    for pose in POSE_NAMES:
        facade.render_landed.emit('ttr', 'Flossbud', pose)
    facade.set_promoted.emit('ttr', 'Flossbud')
    assert editor.canvas.art() is None
    assert all(tile.pixmap() is None for tile in editor.pose_strip.tiles)


def test_switcher_six_slots_keep_edited_and_primary_with_legacy_unchanged(host):
    toons = [_rec(f'Toon {i}', f'74{i:02d}', 'cat', laff=10+i) for i in range(8)]
    editor = _mount(host, _draft(rec=toons[7]), toons, 'Toon 6')
    editor.set_retarget_only(True)
    editor.pill.click()
    names = [r.toon for r in editor.switcher.rows()]
    assert len(names) == 6
    assert {'Toon 6', 'Toon 7'} <= set(names)
    assert editor.switcher.heading_text().startswith('6 of 6')
    assert editor.toon_count() == 6
    editor.set_retarget_only(False)
    editor.pill.click()
    assert len(editor.switcher.rows()) == 8


@pytest.mark.parametrize('save', [False, True])
def test_appearance_close_reports_identity_after_clearing_and_only_once(roster, save):
    closed = []
    roster.appearance_closed.connect(lambda *args: closed.append((args, roster.appearance_sheet.draft())))
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    if save:
        roster.appearance_save_requested.connect(lambda *_: roster.close_sheet())
        roster.sheet.save_button.click()
    else:
        roster.close_sheet()
    roster.close_sheet()
    assert closed == [(('ttr', 'a', 'Flossbud', save), None)]


def test_unclosed_save_does_not_mark_later_cancel_as_saved(roster):
    closed = []
    roster.appearance_closed.connect(lambda *args: closed.append(args))
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    roster.sheet.save_button.click()
    assert closed == []
    roster.close_sheet()
    assert closed == [('ttr', 'a', 'Flossbud', False)]


def test_close_listener_can_reopen_editor_without_its_draft_being_cleared(roster):
    roster.appearance_closed.connect(lambda *_: roster.open_appearance_sheet(
        'ttr', _look(toon='Pepper'), _records(), 'Flossbud'))
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    roster.close_sheet()
    assert roster.appearance_sheet.draft().toon_name == 'Pepper'


def test_retarget_does_not_emit_close_and_final_close_names_last_toon(roster):
    closed = []
    roster.appearance_closed.connect(lambda *args: closed.append(args))
    answer_retarget(roster)
    roster.open_appearance_sheet('ttr', _look(), _records(), 'Flossbud')
    switch_to(roster, 'Pepper')
    assert closed == []
    roster.close_sheet()
    assert closed == [('ttr', 'a', 'Pepper', False)]


def test_account_only_session_has_no_appearance_close(roster):
    closed = []
    roster.appearance_closed.connect(lambda *args: closed.append(args))
    roster.open_account_sheet('ttr', _account(), _records(), 'Flossbud')
    roster.close_sheet()
    assert closed == []


def test_router_retarget_does_not_rebuild_hero_or_change_primary(stage, monkeypatch):
    account = _two_toons(stage)
    tab = stage.launch_tab
    tab._open_appearance_sheet('ttr', account)
    rebuilt = []
    monkeypatch.setattr(tab.grandstand, '_rebuild_lineup', lambda game: rebuilt.append(game))
    tab._on_subject_toon_chosen('ttr', account, 'Hector')
    assert rebuilt == []
    assert tab._recent_toons.primary_name(account) == 'Flossbud'
    assert tab.grandstand.appearance_sheet.draft().toon_name == 'Hector'


def test_return_to_account_waits_for_appearance_close_not_generic_page_change(stage):
    account = _two_toons(stage)
    stage._open_look_from_account(account, 'ttr', 'Hector')
    stage.launch_tab.launcher_sheet_closed.emit()
    assert stage.open_sheet_name() is None
    stage.launch_tab.grandstand.close_sheet()
    assert stage.open_sheet_name() == SHEET_ACCOUNTS
    assert stage.accounts_sheet.account_id() == account
