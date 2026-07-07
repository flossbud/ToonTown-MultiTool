import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


class _StubKeymap:
    def has_conflicts(self, game, idx):
        return (False, [])

    def on_change(self, cb):
        pass

    def get_set_names(self, game="ttr"):
        return ["Default", "Arrows"]


def _sel(qapp):
    from tabs.multitoon._tab import SetSelectorWidget
    return SetSelectorWidget(_StubKeymap())


def test_default_height_is_38(qapp):
    assert _sel(qapp).height() == 38


def test_glass_radius_is_capsule(qapp):
    # paintEvent must use height/2 as radius (true capsule); smoke render.
    w = _sel(qapp)
    w.resize(160, 38)
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtCore import QPoint
    pm = QPixmap(160, 38)
    p = QPainter(pm)
    w.render(p, QPoint(0, 0))      # must not raise
    p.end()


def test_dim_progress_still_applies(qapp):
    w = _sel(qapp)
    w.set_dim_progress(1.0)
    assert w._dim_progress == 1.0


def test_arrow_hit_zone_changes_index(qapp):
    # Right arrow zone advances the index when count > 1.
    w = _sel(qapp)
    w.resize(160, 38)
    before = w.currentIndex()
    assert hasattr(w, "ARROW_ZONE")
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt as QtCore_Qt
    pos = QPointF(w.width() - 5, w.height() / 2)
    ev = QMouseEvent(QEvent.MouseButtonPress, pos, QtCore_Qt.LeftButton,
                      QtCore_Qt.LeftButton, QtCore_Qt.NoModifier)
    w.mousePressEvent(ev)
    assert w.currentIndex() == (before + 1) % w.count()


def test_conflict_marker_still_paints(qapp):
    # set_has_conflict must still flip state and trigger a repaint, and the
    # widget must still render without raising once flagged.
    w = _sel(qapp)
    w.resize(160, 38)
    w.set_has_conflict(True, [("run", "jump")])
    assert w._has_conflict is True
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtCore import QPoint
    pm = QPixmap(160, 38)
    p = QPainter(pm)
    w.render(p, QPoint(0, 0))
    p.end()


def test_paint_scale_still_applies(qapp):
    w = _sel(qapp)
    w.set_paint_scale(1.5)
    assert w._paint_scale == 1.5
    w.resize(200, 38)
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtCore import QPoint
    pm = QPixmap(200, 38)
    p = QPainter(pm)
    w.render(p, QPoint(0, 0))      # must not raise at a non-1.0 scale
    p.end()


def test_public_api_unchanged(qapp):
    w = _sel(qapp)
    w.setCurrentIndex(1)
    assert w.currentIndex() == 1
    assert w.currentText() == "Arrows"
    got = []
    w.index_changed.connect(got.append)
    w._next()
    assert got == [0]
    w.set_toon_game("cc")
    w.set_dimmed(True)
    assert w._dim_progress == 1.0
    w.set_dimmed(False)
    assert w._dim_progress == 0.0
