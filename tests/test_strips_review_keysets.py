"""Stable keyset targets while strip editors and menus are open."""
import pytest

from tests.test_strips_controller import Keymaps, rig, settle
from utils.strips import layout as L


class WritableKeymaps(Keymaps):
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
