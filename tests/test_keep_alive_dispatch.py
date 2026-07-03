"""Unit tests for the per-cycle keep-alive dispatch helper.

The helper resolves (game, action) -> the CLIENT's key per toon and
dispatches via InputService.send_keep_alive_to_window. Outbound mirrors the
router rule: CC movement uses the WASD-lock canonical, everything else uses
set 0. A toon's assigned set never participates - the client only speaks
its own (set-0/config-driven) bindings. Tests stub all transports so no
real Qt event loop or wine bridge is exercised.
"""

from types import SimpleNamespace

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
        input_service=stub_input_service,
    )
    assert fired == 2
    assert ("w1", "space") in stub_input_service.calls
    assert ("w2", "space") in stub_input_service.calls


def test_custom_set_never_participates(stub_input_service, stub_window_manager,
                                        real_keymap, patch_registry):
    """The toon's assigned set is irrelevant: even a set with no binding for
    the action sends the client's set-0 key."""
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    real_keymap.add_set("ttr", name="Minimal")
    # Wipe the 'book' binding on the new set so set 1 has no book key.
    real_keymap.update_set_key("ttr", 1, "book", "")
    patch_registry({"w1": "ttr"})
    _dispatch_keep_alive_cycle(
        action="book",
        fire_toons=[0],
        window_manager=stub_window_manager(["w1"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "Alt_L") in stub_input_service.calls  # set 0, the client binding


def test_rebound_set_still_gets_client_key(stub_input_service, stub_window_manager,
                                            real_keymap, patch_registry):
    """Regression: a set that REBINDS the keep-alive action (jump=Alt_R) must
    not leak its own key to the client. The client's jump is space; a raw
    Alt_R reads as the side-agnostic 'alt' stickerBook binding and toggled
    the book open every keep-alive cycle on the live winbox."""
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    real_keymap.add_set("ttr", name="Arrows")
    real_keymap.update_set_key("ttr", 1, "jump", "Alt_R")
    patch_registry({"w1": "ttr", "w2": "ttr"})
    _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w2", "space") in stub_input_service.calls
    assert ("w2", "Alt_R") not in stub_input_service.calls


def test_unclassified_window_skipped(stub_input_service, stub_window_manager,
                                      real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr"})  # w2 is intentionally not classified
    fired = _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert fired == 1
    assert ("w1", "space") in stub_input_service.calls
    assert ("w2", "space") not in stub_input_service.calls


def test_missing_window_slot_skipped(stub_input_service, stub_window_manager,
                                      real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr"})
    fired = _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1, 2],
        window_manager=stub_window_manager(["w1"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert fired == 1
    assert stub_input_service.calls == [("w1", "space")]


def test_up_alias_resolves_to_forward(stub_input_service, stub_window_manager,
                                       real_keymap, patch_registry):
    """Settings UI stores the 'Move Forward' action as 'up'; the dispatcher
    must alias it to the logical action 'forward'."""
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr"})
    _dispatch_keep_alive_cycle(
        action="up",
        fire_toons=[0],
        window_manager=stub_window_manager(["w1"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "Up") in stub_input_service.calls  # TTR default forward = Up


def test_zero_matches_returns_zero(stub_input_service, stub_window_manager,
                                    real_keymap, patch_registry):
    """All candidates unclassified -> dispatcher returns 0, no calls made."""
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({})  # neither window is classified
    fired = _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert fired == 0
    assert stub_input_service.calls == []


def test_ttr_mixed_sets_forward(stub_input_service, stub_window_manager,
                                 real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    real_keymap.add_set("ttr", name="Arrows")
    real_keymap.update_set_key("ttr", 1, "forward", "Up")
    patch_registry({"w1": "ttr", "w2": "ttr"})
    _dispatch_keep_alive_cycle(
        action="forward",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "Up") in stub_input_service.calls  # TTR default forward = Up
    assert ("w2", "Up") in stub_input_service.calls  # set 0 key, not the toon's set


def test_cc_default_jump_fires_space(stub_input_service, stub_window_manager,
                                      real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "cc", "w2": "cc"})
    _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "space") in stub_input_service.calls
    assert ("w2", "space") in stub_input_service.calls


def test_cc_mixed_sets_forward(stub_input_service, stub_window_manager,
                                real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    real_keymap.add_set("cc", name="Arrows")
    real_keymap.update_set_key("cc", 1, "forward", "Up")
    patch_registry({"w1": "cc", "w2": "cc"})
    _dispatch_keep_alive_cycle(
        action="forward",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "w") in stub_input_service.calls  # CC WASD-lock canonical
    assert ("w2", "w") in stub_input_service.calls  # canonical, not the toon's set


def test_mixed_ttr_cc_book(stub_input_service, stub_window_manager,
                            real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr", "w2": "cc"})
    _dispatch_keep_alive_cycle(
        action="book",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "Alt_L") in stub_input_service.calls   # TTR book = Alt_L
    assert ("w2", "Escape") in stub_input_service.calls  # CC book = Escape


def test_mixed_ttr_cc_jump(stub_input_service, stub_window_manager,
                            real_keymap, patch_registry):
    from tabs.multitoon._tab import _dispatch_keep_alive_cycle
    patch_registry({"w1": "ttr", "w2": "cc"})
    _dispatch_keep_alive_cycle(
        action="jump",
        fire_toons=[0, 1],
        window_manager=stub_window_manager(["w1", "w2"]),
        keymap_manager=real_keymap,
        input_service=stub_input_service,
    )
    assert ("w1", "space") in stub_input_service.calls
    assert ("w2", "space") in stub_input_service.calls
