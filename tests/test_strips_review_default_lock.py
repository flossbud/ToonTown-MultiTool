"""The strip editor must preserve the game's imported key table."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetricsF, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from tests.test_strips_controller import (Backend, Strategy, Settings, rig, settle, real_keymaps,
                                          _real_session, open_editor)
from tests.test_strips_review_keysets import WritableKeymaps
from tests.test_strips_popovers import MODEL
from utils import chord_capture_state
from utils.strips import paint
from utils.strips.popovers.editor import KeysetEditor
from utils.strips.popovers.surface import PopoverSurface
from utils.widgets.keysets import rules

NOTE = "These are the game's own keys. Change them in the game's options."


def assembled_image(card):
    surface = PopoverSurface(Strategy(), Backend(), card)
    surface.present(QPoint(0, 0), None)
    settle()
    image = QImage(surface.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    surface.render(image)
    surface.dismiss()
    return image


@pytest.fixture
def no_game_config(monkeypatch):
    monkeypatch.setattr('utils.ttr_settings.locate_settings_file', lambda **_: None)
    monkeypatch.setattr('services.ttr_login_service.find_engine_path', lambda: '')
    monkeypatch.setattr('services.wine_runtimes.discover_cc_installs', lambda: [])


@pytest.mark.parametrize('kind', ['list', 'keys'])
def test_locked_first_set_has_no_capture_or_write_even_for_forced_bind(rig, no_game_config, kind):
    km = WritableKeymaps()
    km.sets['ttr'][0]['book'] = 'F8'
    settings = Settings(last_detected_keymap={'book': 'F8'}, keyset_editor_layout=kind)
    _, controller, _ = rig(keymaps=km, settings=settings)
    card = controller.open_editor('101', 1)
    assert card.model().read_only
    states = []
    card.capture_changed.connect(states.append)
    zone = ('cap', 'book') if kind == 'list' else ('key', 'q')
    pos = card.zone_rect(*zone).center().toPoint()
    QTest.mouseMove(card, pos)
    assert card._hover is None
    assert card.cursor().shape() == Qt.ArrowCursor
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, pos)
    card.begin_capture('book')
    assert card.listening() == '' and QWidget.keyboardGrabber() is None
    assert not chord_capture_state.is_active() and states == []
    before = km.get_sets('ttr')
    card.bind_requested.emit('book', 'F10')
    assert km.get_sets('ttr') == before
    assert km.get_sets('ttr')[0]['book'] == 'F8'


@pytest.mark.parametrize('number,config', [(2, True), (1, False)])
def test_other_set_and_first_set_without_game_config_still_bind(rig, no_game_config, number, config):
    km = WritableKeymaps()
    settings = Settings(last_detected_keymap={'book': 'F8'} if config else {})
    _, controller, _ = rig(keymaps=km, settings=settings)
    card = controller.open_editor('101', number)
    assert not card.model().read_only
    card.begin_capture('book')
    assert card.listening() == 'book' and QWidget.keyboardGrabber() is card
    QTest.keyClick(card, Qt.Key_F10)
    settle()
    assert km.get_sets('ttr')[number - 1]['book'] == 'F10'
    assert QWidget.keyboardGrabber() is None


def test_lock_is_rechecked_when_opening_and_at_write(rig, no_game_config):
    settings = Settings()
    km = WritableKeymaps()
    _, controller, _ = rig(keymaps=km, settings=settings)
    card = controller.open_editor('101', 1)
    assert not card.model().read_only
    # A config import after opening must also defeat an already queued bind.
    settings.set('last_detected_keymap', {'book': 'F8'})
    before = km.get_sets('ttr')
    card.bind_requested.emit('book', 'F10')
    assert km.get_sets('ttr') == before
    controller.popovers.close('101')
    card = controller.open_editor('101', 1)
    assert card.model().read_only
    settings.set('last_detected_keymap', {})
    controller.popovers.close('101')
    assert not controller.open_editor('101', 1).model().read_only


def test_lock_uses_the_toons_game_and_current_settings(rig, monkeypatch):
    settings = Settings()
    calls = []
    def locked(game, manager):
        calls.append((game, manager))
        return game == 'cc'
    monkeypatch.setattr(rules, 'default_set_locked', locked)
    _, controller, _ = rig(keymaps=WritableKeymaps(), settings=settings)
    assert controller.open_editor('103', 1).model().read_only
    assert not controller.open_editor('101', 1).model().read_only
    assert calls == [('cc', settings), ('ttr', settings)]


@pytest.mark.parametrize('style', ['neon', 'flat'])
@pytest.mark.parametrize('scale', [1.0, 1.25, 1.5])
@pytest.mark.parametrize('kind', ['list', 'keys'])
def test_locked_card_keeps_width_and_fits_exact_instruction(qapp, style, scale, kind):
    card = KeysetEditor(replace(MODEL, read_only=True), kind, style, scale)
    unlocked = KeysetEditor(MODEL, kind, style, scale)
    assert card.sizeHint().width() == unlocked.sizeHint().width()
    assert card._note_text == NOTE
    fm = QFontMetricsF(card._fonts()['hint'])
    bounds = fm.boundingRect(card._note_rect, Qt.TextWordWrap | Qt.AlignLeft, NOTE)
    assert bounds.height() <= card._note_rect.height() + 0.01
    assert card._card.contains(card._note_rect)
    # Rendering through the real card painter also covers dim keys in both looks.
    locked_image = assembled_image(card)
    unlocked_image = assembled_image(unlocked)
    zone = ('cap', 'forward') if kind == 'list' else ('key', 'w')
    cap = card.zone_rect(*zone)
    x, y = round(cap.left() + 3 * scale), round(cap.top() + 3 * scale)
    assert locked_image.pixelColor(x, y) != unlocked_image.pixelColor(x, y)


def test_refresh_to_locked_cancels_existing_capture(qapp):
    card = KeysetEditor(MODEL)
    card.show()
    card.begin_capture('book')
    assert QWidget.keyboardGrabber() is card
    card.set_model(replace(MODEL, read_only=True))
    assert card.listening() == '' and QWidget.keyboardGrabber() is None
    assert not chord_capture_state.is_active()


def test_locked_card_still_allows_inspection_layout_switch_and_close(qapp):
    card = KeysetEditor(replace(MODEL, read_only=True))
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect('kind', 'keys').center().toPoint())
    assert card.kind() == 'keys'
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect('chip', 'book').center().toPoint())
    assert card.selected_action() == 'book'
    closed = []
    card.close_requested.connect(lambda: closed.append(True))
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect('close').center().toPoint())
    assert closed == [True]


def test_locked_keyboard_keeps_selected_fkey_hint_without_edit_prompt(qapp, monkeypatch):
    model = replace(MODEL, read_only=True,
                    binds=tuple((a, 'F8' if a == 'book' else k) for a, k in MODEL.binds))
    card = KeysetEditor(model, 'keys')
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier,
                     card.zone_rect('chip', 'book').center().toPoint())
    texts = []
    draw = paint._text
    def record(p, rect, text, *args, **kwargs):
        texts.append(text)
        return draw(p, rect, text, *args, **kwargs)
    monkeypatch.setattr(paint, '_text', record)
    assembled_image(card)
    assert 'Book is ' in texts and 'F8' in texts
    assert not any('rebind' in text for text in texts)


@pytest.mark.parametrize('number', [1, 2, 3])
@pytest.mark.parametrize('locked', [False, True])
def test_two_toons_edit_the_button_number_not_their_active_set(
        rig, real_keymaps, no_game_config, number, locked):
    km = real_keymaps
    session = _real_session(km)
    ids = km.get_set_ids('ttr')
    session.set_keyset('101', ids[0])
    session.set_keyset('102', ids[1])
    settings = Settings(last_detected_keymap={'book': 'F8'} if locked else {})
    _, controller, _ = rig(session, km, settings)
    assert [controller.follower.surface(wid).strip.model().active
            for wid in ('101', '102')] == [1, 2]
    for wid, key, expected in [('101', Qt.Key_F7, 'F7'), ('102', Qt.Key_F9, 'F9')]:
        before = km.get_sets('ttr')
        card = open_editor(controller, wid, number)
        assert card.model().number == number
        card.begin_capture('book')
        if locked and number == 1:
            assert card.listening() == ''
            card.bind_requested.emit('book', 'F10')
            assert km.get_sets('ttr') == before
        else:
            assert card.listening() == 'book'
            QTest.keyClick(card, key)
            settle()
            after = km.get_sets('ttr')
            assert after[number - 1]['book'] == expected
            assert all(entry == before[i] for i, entry in enumerate(after)
                       if i != number - 1)
            changed = dict(after[number - 1])
            changed['book'] = before[number - 1]['book']
            assert changed == before[number - 1]
        assert session.toon(wid).keyset_id == ids[0 if wid == '101' else 1]
