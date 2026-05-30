import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.window_layout import clamp_window_height


def test_default_geometry_uses_clamp_contract():
    # Documents the contract __init__ relies on: target 862, margin 48.
    assert clamp_window_height(1080) == 862
    assert clamp_window_height(800) == 752
