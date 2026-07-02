"""TaskbarRepresentative: the float-UI taskbar/Alt-Tab stand-in (offscreen)."""
from utils.overlay.backend import NoOpOverlayBackend


def test_noop_backend_accepts_representative_hint_calls():
    """The protocol additions must exist on the NoOp base (stub backends in
    other suites inherit them) and never raise."""
    b = NoOpOverlayBackend()
    b.set_rep_initial_state(object())
    b.set_window_opacity(object(), 0.0)
