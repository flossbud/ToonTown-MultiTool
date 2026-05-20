"""Unit tests for the per-cycle keep-alive dispatch helper.

The helper resolves (game, set, action) -> key per toon and dispatches via
InputService.send_keep_alive_to_window. Tests stub all transports so no
real Qt event loop or wine bridge is exercised.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_input_service():
    svc = SimpleNamespace()
    svc.calls = []
    svc.send_keep_alive_to_window = lambda wid, key: svc.calls.append((wid, key))
    return svc


@pytest.fixture
def stub_window_manager():
    def make(window_ids):
        wm = SimpleNamespace()
        wm.get_window_ids = lambda: list(window_ids)
        return wm
    return make


@pytest.fixture
def real_keymap(monkeypatch, tmp_path):
    """Fresh KeymapManager backed by a tmp config dir so we never touch real config."""
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.keymap_manager import KeymapManager
    return KeymapManager()


@pytest.fixture
def patch_registry(monkeypatch):
    def patch(mapping):
        from utils.game_registry import GameRegistry
        monkeypatch.setattr(
            GameRegistry.instance(),
            "get_game_for_window",
            lambda wid: mapping.get(str(wid)),
        )
    return patch


def test_ttr_default_jump_fires_space_to_both(stub_input_service, stub_window_manager,
                                              real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr", "w2": "ttr"})
    fired = _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        assignments=[0, 0],
        input_service=stub_input_service,
    )
    assert fired == 2
    assert ("w1", "space") in stub_input_service.calls
    assert ("w2", "space") in stub_input_service.calls
