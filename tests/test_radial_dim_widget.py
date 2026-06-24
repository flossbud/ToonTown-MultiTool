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


def test_dim_frame_monotonic_scale():
    from utils.overlay.radial_menu import _dim_frame
    vals = [_dim_frame(t)[1] for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


def test_radial_anim_enabled_off_when_kill_switch(monkeypatch):
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")
    from utils.overlay.radial_menu import radial_anim_enabled
    assert radial_anim_enabled() is False


def test_radial_anim_enabled_off_when_reduced_motion(monkeypatch):
    monkeypatch.delenv("TTMT_NO_RADIAL_ANIM", raising=False)
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from utils.overlay.radial_menu import radial_anim_enabled
    assert radial_anim_enabled() is False


def test_radial_anim_enabled_on_by_default(monkeypatch):
    monkeypatch.delenv("TTMT_NO_RADIAL_ANIM", raising=False)
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    from utils.overlay.radial_menu import radial_anim_enabled
    assert radial_anim_enabled() is True


def test_set_backdrop_none_builds_veil_only_and_paints():
    _app()
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.set_backdrop(None)
    w.progress = 1.0
    assert w._frost is not None and not w._frost.isNull()
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    w.render(img, QPoint(0, 0))   # paintEvent must not raise
    assert img.pixelColor(100, 100).alpha() > 0   # the veil actually painted


def test_set_backdrop_pixmap_builds_frost():
    _app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    raw = QPixmap(200, 200); raw.fill(Qt.red)
    w.set_backdrop(raw)
    assert w._frost is not None and not w._frost.isNull()


def test_reveal_and_close_snap_when_not_animated():
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200); w.set_backdrop(None)
    w.start_reveal(animate=False)
    assert w.progress == 1.0
    w.start_close(animate=False)
    assert w.progress == 0.0


def test_reveal_animate_true_starts_animation():
    _app()
    from PySide6.QtCore import QAbstractAnimation
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200); w.set_backdrop(None)
    w.start_reveal(animate=True)
    assert w._anim is not None
    assert w._anim.state() == QAbstractAnimation.Running
    w._stop_anim()   # clean up
    assert w._anim is None


def test_begin_close_emits_closing(monkeypatch):
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")   # synchronous close path
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    seen = []
    w.closing.connect(lambda: seen.append(1))
    w.start_reveal()
    w._begin_close()
    assert seen == [1]
