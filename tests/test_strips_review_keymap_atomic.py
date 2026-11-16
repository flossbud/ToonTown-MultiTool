"""Stable-ID binding writes in the keymap manager."""
import pytest
from utils.keymap_manager import KeymapManager


@pytest.fixture
def keymaps(tmp_path, monkeypatch):
    monkeypatch.setenv('TTMT_CONFIG_DIR', str(tmp_path / 'config'))
    manager = KeymapManager()
    manager.add_set('ttr')
    manager.add_set('ttr')
    return manager


def test_unknown_id_does_not_write_or_notify(keymaps):
    before = keymaps.get_sets('ttr')
    seen = []
    keymaps.on_change(lambda: seen.append(True))
    assert keymaps.update_set_key_by_id('ttr', 'missing', 'forward', 'z') is False
    assert keymaps.get_sets('ttr') == before
    assert seen == []


def test_id_write_after_reorder_targets_original_set_and_notifies_unlocked(keymaps):
    ids = keymaps.get_set_ids('ttr')
    keymaps.move_set('ttr', ids[1], 2)
    seen = []
    # This callback takes the manager lock: notification must happen after release.
    keymaps.on_change(lambda: seen.append(keymaps.get_sets('ttr')))
    assert keymaps.update_set_key_by_id('ttr', ids[1], 'forward', 'z') is True
    assert keymaps.get_set('ttr', 2)['forward'] == 'z'
    assert keymaps.get_set('ttr', 1)['forward'] != 'z'
    assert len(seen) == 1
    assert keymaps.update_set_key_by_id('ttr', ids[1], 'forward', 'z') is True
    assert len(seen) == 1


def test_deleted_id_is_rejected_and_surviving_id_follows_its_shift(keymaps):
    ids = keymaps.get_set_ids('ttr')
    keymaps.delete_set('ttr', 1)
    assert keymaps.update_set_key_by_id('ttr', ids[1], 'forward', 'z') is False
    assert keymaps.get_set('ttr', 1)['forward'] != 'z'
    assert keymaps.update_set_key_by_id('ttr', ids[2], 'forward', 'x') is True
    assert keymaps.get_set('ttr', 1)['forward'] == 'x'
