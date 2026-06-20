from utils.overlay.backend import OverlayBackend, NoOpOverlayBackend, get_overlay_backend

def test_noop_is_unavailable_and_safe():
    b = NoOpOverlayBackend()
    assert b.is_available() is False
    b.apply_input_region(None, None); b.clear_input_region(None); b.set_overlay_hints(None)  # no raise

def test_factory_returns_backend_with_interface():
    b = get_overlay_backend()
    for m in ("is_available", "apply_input_region", "clear_input_region", "set_overlay_hints"):
        assert callable(getattr(b, m))
