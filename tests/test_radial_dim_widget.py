import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="run under QT_QPA_PLATFORM=offscreen",
)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fixture():
    from PySide6.QtWidgets import QWidget
    parent = QWidget(); parent.resize(800, 600)
    emblem = QWidget(parent); emblem.resize(120, 120); emblem.move(340, 240)
    return parent, emblem


def test_dim_frame_endpoints():
    from utils.overlay.radial_menu import _dim_frame
    o0, s0 = _dim_frame(0.0)
    o1, s1 = _dim_frame(1.0)
    assert o0 == 0.0 and abs(s0 - 0.12) < 1e-9
    assert abs(o1 - 1.0) < 1e-9 and abs(s1 - 1.0) < 1e-9


def test_dim_frame_monotonic_opacity():
    from utils.overlay.radial_menu import _dim_frame
    vals = [_dim_frame(t)[0] for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
