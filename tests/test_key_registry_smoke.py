from utils.key_registry import (
    NAMED_KEY_REGISTRY, NAMED_KEYSYMS_FROM_REGISTRY,
    PASSTHROUGH_KEYSYMS, PYNPUT_NAME_MAP_BASE, DISPLAY_NAMES_FROM_REGISTRY,
)

def test_registry_importable_and_non_empty():
    assert len(NAMED_KEY_REGISTRY) > 40
    assert "Home" in NAMED_KEYSYMS_FROM_REGISTRY
    assert "F1" in NAMED_KEYSYMS_FROM_REGISTRY
    assert "KP_0" in NAMED_KEYSYMS_FROM_REGISTRY
    assert isinstance(PASSTHROUGH_KEYSYMS, tuple)
    assert "home" in PYNPUT_NAME_MAP_BASE
    assert "Prior" in DISPLAY_NAMES_FROM_REGISTRY
