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


# --- _dim_frame + radial_anim_enabled (unchanged helpers) --------------------

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


# --- drop-shadow backdrop ----------------------------------------------------

def test_shadow_built_lazily_on_first_paint():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    assert w._shadow is None                 # nothing built until painted
    w.progress = 1.0
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.render(pm, QPoint(0, 0))               # paintEvent must not raise
    assert w._shadow is not None and not w._shadow.isNull()


def test_shadow_is_translucent_dark_disc():
    _app()
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.progress = 1.0
    img = QImage(w.size(), QImage.Format_ARGB32); img.fill(QColor(0, 0, 0, 0))
    w.render(img, QPoint(0, 0))
    center = img.pixelColor(100, 100)
    assert 0 < center.alpha() < 255          # soft, not opaque
    assert center.red() < 60 and center.green() < 60 and center.blue() < 60  # dark
    assert img.pixelColor(2, 2).alpha() == 0 # fades to nothing before the edge


def test_shadow_pixmap_keeps_alpha():
    # Guards the QImage-composite discipline: build on ARGB32_Premultiplied so the
    # shadow keeps a real alpha channel (an opaque QPixmap reads back solid).
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    s = w._build_shadow()
    assert s is not None and not s.isNull()
    assert s.hasAlphaChannel()
    img = s.toImage()
    cx, cy = s.width() // 2, s.height() // 2
    assert 0 < img.pixelColor(cx, cy).alpha() < 255
    assert img.pixelColor(2, 2).alpha() == 0


def test_shadow_build_is_deterministic():
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    a = w._build_shadow(); b = w._build_shadow()
    assert a is not None and b is not None
    assert a.toImage() == b.toImage()


def test_paint_cache_uses_logical_size_not_physical():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QSize, QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    # Simulate a dpr=2 shadow: physical 400 but logical (cache key) 200.
    fake = QPixmap(400, 400); fake.setDevicePixelRatio(2.0); fake.fill(QColor(1, 2, 3, 200))
    w._shadow = fake
    w._shadow_size = QSize(200, 200)
    w._shadow_dpr = float(w.devicePixelRatioF() or 1.0)
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.progress = 1.0
    w.render(pm, QPoint(0, 0))
    assert w._shadow is fake                 # logical key matches -> no rebuild


def test_paint_rebuilds_when_dpr_changes():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QSize, QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    fake = QPixmap(200, 200); fake.fill(QColor(1, 2, 3, 200))
    w._shadow = fake
    w._shadow_size = QSize(200, 200)
    w._shadow_dpr = float(w.devicePixelRatioF() or 1.0) + 1.0   # stale dpr
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.progress = 1.0
    w.render(pm, QPoint(0, 0))
    assert w._shadow is not fake             # rebuilt: cached dpr != current dpr


def test_shadow_rebuilds_after_resize():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(0, 0)    # 0x0 / pre-layout
    w.progress = 1.0
    pm0 = QPixmap(10, 10); pm0.fill(QColor(0, 0, 0, 0))
    w.render(pm0, QPoint(0, 0))
    assert w._shadow is None                 # nothing built at 0x0
    w.resize(200, 200)
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.render(pm, QPoint(0, 0))               # lazy rebuild on paint
    assert w._shadow is not None
    assert abs(w._shadow.deviceIndependentSize().width() - 200.0) < 0.5


def test_shadow_translucent_under_hidpi_scale_factor():
    # Regression for the HiDPI opaque bug: at QT_SCALE_FACTOR=2 a QPixmap composite
    # could read back fully opaque. Build the shadow in a fresh interpreter with the
    # scale factor set before QApplication, and assert it is a real translucent disc.
    import os
    import sys
    import subprocess
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    script = (
        "import os\n"
        "os.environ['QT_QPA_PLATFORM']='offscreen'\n"
        "os.environ['QT_SCALE_FACTOR']='2'\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app=QApplication([])\n"
        "from utils.overlay.radial_menu import RadialDimWidget\n"
        "w=RadialDimWidget(); w.resize(200,200)\n"
        "s=w._build_shadow(); im=s.toImage()\n"
        "assert abs(w.devicePixelRatioF()-2.0)<1e-6, 'scale factor not applied'\n"
        "assert s.hasAlphaChannel(), 'shadow lost alpha at hidpi'\n"
        "c=im.pixelColor(s.width()//2, s.height()//2).alpha()\n"
        "corner=im.pixelColor(2,2).alpha()\n"
        "assert 0 < c < 255, f'center not translucent: {c}'\n"
        "assert corner == 0, f'corner not transparent: {corner}'\n"
        "print('HIDPI_OK')\n"
    )
    env = dict(os.environ)
    env["TTMT_NO_VENV_REEXEC"] = "1"
    env.pop("QT_SCALE_FACTOR", None)   # let the child set it before QApplication
    r = subprocess.run([sys.executable, "-c", script], cwd=str(repo),
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (
        f"child exited {r.returncode}: stdout={r.stdout!r} stderr={r.stderr!r}")
    assert "HIDPI_OK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_reveal_and_close_snap_when_not_animated():
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.start_reveal(animate=False)
    assert w.progress == 1.0
    w.start_close(animate=False)
    assert w.progress == 0.0


def test_reveal_animate_true_starts_animation():
    _app()
    from PySide6.QtCore import QAbstractAnimation
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
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


def test_windowed_show_centered_reveals_and_collapses(monkeypatch):
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")   # snap reveal/close
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    emblem.raise_()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    host.show_centered()
    assert host._dim is not None
    assert host._dim.progress == 1.0           # reveal snapped to shown
    host.menu.closing.emit()                   # fly-back begins
    assert host._dim.progress == 0.0           # dim collapses in step
