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


def test_set_backdrop_none_is_glassy_not_dark():
    _app()
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.set_backdrop(None)
    w.progress = 1.0
    assert w._frost is not None and not w._frost.isNull()
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    w.render(img, QPoint(0, 0))                 # paintEvent must not raise
    c = img.pixelColor(100, 100)
    assert 0 < c.alpha() < 255                  # translucent disc, not opaque
    assert c.red() > 60 and c.green() > 60 and c.blue() > 60   # milky, not flat dark


def test_frost_build_is_deterministic():
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    a = w._build_frost(None)
    b = w._build_frost(None)
    assert a is not None and b is not None
    assert a.toImage() == b.toImage()          # seeded grain => identical builds


def test_paint_cache_uses_logical_size_not_physical():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QSize, QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.set_backdrop(None)
    # Simulate a dpr=2 frost: physical 400 but logical (cache key) 200.
    fake = QPixmap(400, 400); fake.setDevicePixelRatio(2.0); fake.fill(QColor(1, 2, 3, 200))
    w._frost = fake
    w._frost_size = QSize(200, 200)
    img = QPixmap(w.size()); img.fill(QColor(0, 0, 0, 0))
    w.progress = 1.0
    w.render(img, QPoint(0, 0))
    # Must NOT rebuild: logical key (200) == widget size (200), despite physical 400.
    assert w._frost is fake


def test_paint_rebuilds_when_dpr_changes():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QSize, QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.set_backdrop(None)
    fake = QPixmap(200, 200); fake.fill(QColor(1, 2, 3, 200))
    w._frost = fake
    w._frost_size = QSize(200, 200)
    # Stale dpr derived from the REAL dpr (+1) so this holds regardless of the
    # environment's scale factor (do not hard-code an assumed offscreen dpr).
    w._frost_dpr = float(w.devicePixelRatioF() or 1.0) + 1.0
    img = QPixmap(w.size()); img.fill(QColor(0, 0, 0, 0))
    w.progress = 1.0
    w.render(img, QPoint(0, 0))
    assert w._frost is not fake            # rebuilt because cached dpr != current dpr


def test_frost_with_source_is_translucent_disc():
    _app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QImage, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    raw = QPixmap(200, 200); raw.fill(Qt.red)
    w.set_backdrop(raw)
    w.progress = 1.0
    assert w._frost is not None and not w._frost.isNull()
    img = QImage(w.size(), QImage.Format_ARGB32); img.fill(QColor(0, 0, 0, 0))
    w.render(img, QPoint(0, 0))
    assert 0 < img.pixelColor(100, 100).alpha() < 255
    assert img.pixelColor(2, 2).alpha() == 0   # corner outside the disc -> clear


def test_frost_pixmap_keeps_alpha_and_carves_disc():
    # Direct check on the frost pixmap (not via render): the mask must actually
    # carve a translucent disc. Guards the QImage-composite fix - a QPixmap
    # surface drops its alpha when opaque and silently no-ops DestinationIn.
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    w.set_backdrop(None)
    f = w._frost
    assert f is not None and not f.isNull()
    assert f.hasAlphaChannel()                      # alpha preserved through compositing
    img = f.toImage()
    cx, cy = f.width() // 2, f.height() // 2
    assert 0 < img.pixelColor(cx, cy).alpha() < 255  # translucent center, not opaque
    assert img.pixelColor(2, 2).alpha() == 0         # corner carved away (real disc)


def test_frost_translucent_under_hidpi_scale_factor():
    # Regression for the HiDPI opaque-disc bug: at QT_SCALE_FACTOR=2 a QPixmap
    # composite produced a fully opaque square. Run a fresh interpreter with the
    # scale factor set (it must be set before the QApplication is created, which
    # this process already did at dpr=1) and assert the frost is a real disc.
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
        "w=RadialDimWidget(); w.resize(200,200); w.set_backdrop(None)\n"
        "f=w._frost; im=f.toImage()\n"
        "assert abs(w.devicePixelRatioF()-2.0)<1e-6, 'scale factor not applied'\n"
        "assert f.hasAlphaChannel(), 'frost lost alpha at hidpi'\n"
        "c=im.pixelColor(f.width()//2, f.height()//2).alpha()\n"
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


def test_set_backdrop_pixmap_builds_frost():
    _app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(200, 200)
    raw = QPixmap(200, 200); raw.fill(Qt.red)
    w.set_backdrop(raw)
    assert w._frost is not None and not w._frost.isNull()


def test_frost_rebuilds_when_size_unset_at_set_backdrop():
    _app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(0, 0)        # 0x0 / pre-layout at set_backdrop time
    raw = QPixmap(50, 50); raw.fill(Qt.red)
    w.set_backdrop(raw)
    assert w._frost is None                      # nothing built at 0x0
    w.resize(200, 200)
    w.progress = 1.0
    pm = QPixmap(w.size()); pm.fill(Qt.transparent); w.render(pm)   # lazy rebuild on paint
    # Compare LOGICAL size: _frost is dpr-backed (physical px), so .size() is 200
    # at dpr 1 but 400 at dpr 2 - deviceIndependentSize() is 200 at any dpr.
    assert w._frost is not None
    assert abs(w._frost.deviceIndependentSize().width() - 200.0) < 0.5


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


def test_windowed_show_centered_frosts_and_collapses(monkeypatch):
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")   # snap reveal/close
    _app()
    from utils.overlay.windowed_wheel import WindowedWheelHost
    parent, emblem = _fixture()
    emblem.raise_()
    host = WindowedWheelHost(parent, emblem, emblem_diameter=120)
    host.show_centered()
    assert host._dim is not None
    assert host._dim._frost is not None        # a frost composite was baked
    assert host._dim.progress == 1.0           # reveal snapped to shown
    host.menu.closing.emit()                   # fly-back begins
    assert host._dim.progress == 0.0           # dim collapses in step
