"""Stable keyset targets while strip editors and menus are open."""
import pytest

from tests.test_strips_controller import Keymaps, rig, settle, real_keymaps, _real_session
from utils.strips import layout as L


class WritableKeymaps(Keymaps):
    def update_set_key_by_id(self, game, set_id, action, key):
        for index, entry in enumerate(self.sets[game]):
            if entry['id'] == set_id:
                self.update_set_key(game, index, action, key)
                return True
        return False

    def update_set_key(self, game, index, action, key):
        self.sets[game][index][action] = key
        self.notify()


@pytest.mark.parametrize('change', ['reorder', 'delete'])
def test_editor_never_rebinds_a_replacement_at_the_same_number(rig, change):
    km = WritableKeymaps()
    km.sets['ttr'][1]['forward'] = 'a'
    km.sets['ttr'][2]['forward'] = 'b'
    _, controller, _ = rig(keymaps=km)
    card = controller.open_editor('101', 2)
    original = km.sets['ttr'][1]
    if change == 'reorder':
        km.sets['ttr'][1:3] = reversed(km.sets['ttr'][1:3])
    else:
        km.sets['ttr'].pop(1)
    km.notify()
    # A key event already delivered to the old card must not write a new target.
    card.bind_requested.emit('forward', 'z')
    assert km.sets['ttr'][1]['forward'] == 'b'
    assert original['forward'] == 'a'
    assert controller.popovers.open_tag('101') == ''


def test_binding_uses_current_identity_even_before_change_notification(rig):
    km = WritableKeymaps()
    km.sets['ttr'][1]['forward'] = 'a'
    km.sets['ttr'][2]['forward'] = 'b'
    _, controller, _ = rig(keymaps=km)
    card = controller.open_editor('101', 2)
    km.sets['ttr'].pop(1)
    # Manager edits may arrive from another thread before its queued notification.
    card.bind_requested.emit('forward', 'z')
    assert km.sets['ttr'][1]['forward'] == 'b'


def test_numbered_menu_closes_when_keyset_membership_changes(rig):
    km = WritableKeymaps()
    _, controller, _ = rig(keymaps=km)
    controller._on_context('101', L.KEYSET, 2)
    assert controller.popovers.open_tag('101') == 'set:2'
    km.sets['ttr'].pop(1)
    km.notify()
    settle()
    assert controller.popovers.open_tag('101') == ''


@pytest.mark.parametrize('change', ['reorder', 'delete'])
def test_manager_mutation_between_editor_check_and_write_keeps_stable_target(rig, real_keymaps, change, monkeypatch):
    km = real_keymaps
    target = km.get_set_ids('ttr')[1]
    index_write = km.update_set_key
    id_write = km.update_set_key_by_id

    def mutate():
        if change == 'reorder':
            km.move_set('ttr', target, 2)
        else:
            km.delete_set('ttr', 1)

    def by_index(game, index, action, key):
        mutate()
        return index_write(game, index, action, key)

    def by_id(game, set_id, action, key):
        mutate()
        return id_write(game, set_id, action, key)

    monkeypatch.setattr(km, 'update_set_key', by_index)
    monkeypatch.setattr(km, 'update_set_key_by_id', by_id)
    _, controller, _ = rig(_real_session(km), km)
    card = controller.open_editor('101', 2)
    card.bind_requested.emit('forward', 'z')
    entries = km.get_sets('ttr')
    if change == 'reorder':
        assert next(e for e in entries if e['id'] == target)['forward'] == 'z'
    assert all(e.get('forward') != 'z' for e in entries if e['id'] != target)
