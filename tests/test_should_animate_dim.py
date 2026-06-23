import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from tabs.multitoon._compact_layout import _should_animate_dim


def test_animate_only_on_lit_to_dim_transition():
    assert _should_animate_dim(0.0, 1.0, visible=True, effects_off=False) is True


def test_no_animate_dim_to_lit():
    assert _should_animate_dim(1.0, 0.0, visible=True, effects_off=False) is False


def test_no_animate_first_paint():
    assert _should_animate_dim(None, 1.0, visible=True, effects_off=False) is False


def test_no_animate_when_hidden():
    assert _should_animate_dim(0.0, 1.0, visible=False, effects_off=False) is False


def test_no_animate_when_effects_off():
    assert _should_animate_dim(0.0, 1.0, visible=True, effects_off=True) is False
