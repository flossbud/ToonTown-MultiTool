import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QApplication, QListView, QStyle,
                               QStyleOptionViewItem)

from utils.widgets.logs_console.delegate import LINE_H, LogLineDelegate
from utils.widgets.logs_console.model import LogLineModel
from utils.widgets.logs_console.proxy import LogFilterProxy
from utils.widgets.logs_console.records import make_line


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def rig(qapp):
    model = LogLineModel()
    proxy = LogFilterProxy()
    proxy.setSourceModel(model)
    view = QListView()
    view.setModel(proxy)
    delegate = LogLineDelegate(view)
    view.setItemDelegate(delegate)
    view.resize(600, 300)
    view.show()  # offscreen: viewport().width() tracks resize() only once shown
    QApplication.processEvents()
    return model, proxy, view, delegate


def _opt(view):
    opt = QStyleOptionViewItem()
    opt.rect = view.viewport().rect()
    return opt


def test_line_h_is_compact_13px_at_145(qapp):
    assert LINE_H == round(13 * 1.45)   # 19


def test_single_line_height(rig):
    model, proxy, view, delegate = rig
    model.append(make_line("short", now=datetime(2026, 7, 9, 12, 0)))
    h = delegate.sizeHint(_opt(view), proxy.index(0, 0)).height()
    assert h == LINE_H + 2  # + 2*PAD_V(1)


def test_long_message_wraps_taller(rig):
    model, proxy, view, delegate = rig
    model.append(make_line("[Launch] " + "word " * 80,
                           now=datetime(2026, 7, 9, 12, 0)))
    h = delegate.sizeHint(_opt(view), proxy.index(0, 0)).height()
    assert h > 2 * LINE_H  # wrapped over several lines


def test_narrower_view_means_taller_row(rig):
    model, proxy, view, delegate = rig
    model.append(make_line("[Launch] " + "word " * 40,
                           now=datetime(2026, 7, 9, 12, 0)))
    idx = proxy.index(0, 0)
    wide = delegate.sizeHint(_opt(view), idx).height()
    view.resize(300, 300)
    QApplication.processEvents()
    narrow = delegate.sizeHint(_opt(view), idx).height()
    assert narrow > wide


def test_sizehint_and_paint_share_the_wrap_width(rig, monkeypatch):
    model, proxy, view, delegate = rig
    model.append(make_line("[Launch] " + "word " * 40,
                           now=datetime(2026, 7, 9, 12, 0)))
    idx = proxy.index(0, 0)
    seen = []
    real = delegate._msg_w
    monkeypatch.setattr(delegate, "_msg_w",
                        lambda line, w: seen.append(w) or real(line, w))
    opt = _opt(view)
    delegate.sizeHint(opt, idx)
    img = QImage(600, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    opt.rect.setHeight(delegate.sizeHint(opt, idx).height())
    delegate.paint(p, opt, idx)
    p.end()
    assert len(set(seen)) == 1, f"sizeHint/paint widths diverged: {set(seen)}"


def test_tag_only_line_is_single_height(rig):
    model, proxy, view, delegate = rig
    model.append(make_line("[Service]", now=datetime(2026, 7, 9, 12, 0)))
    h = delegate.sizeHint(_opt(view), proxy.index(0, 0)).height()
    assert h == LINE_H + 2  # empty message still occupies one line


def test_hover_paints_copy_glyph_region(rig):
    model, proxy, view, delegate = rig
    # Short message: its ink stays far from the right-edge glyph region.
    model.append(make_line("[Service] ready", now=datetime(2026, 7, 9, 12, 0)))
    idx = proxy.index(0, 0)
    h = delegate.sizeHint(_opt(view), idx).height()

    def render(hovered):
        img = QImage(view.viewport().width(), h,
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        opt = _opt(view)
        opt.rect.setHeight(h)
        if hovered:
            opt.state |= QStyle.State_MouseOver
        delegate.paint(p, opt, idx)
        p.end()
        return img

    def right_edge_ink(img, min_alpha):
        x0 = img.width() - 30
        return any(img.pixelColor(x, y).alpha() > min_alpha
                   for y in range(img.height())
                   for x in range(x0, img.width()))

    # min_alpha 40 discriminates the glyph (~112) from the faint hover-row
    # tint (~12) so the assertion proves the GLYPH painted, not just the tint.
    assert right_edge_ink(render(True), min_alpha=40)   # hover: glyph ink
    assert not right_edge_ink(render(False), min_alpha=0)  # no hover: empty


def test_paint_smoke_and_copied_state(rig):
    model, proxy, view, delegate = rig
    model.append(make_line("[TTR API] Login OK", now=datetime(2026, 7, 9, 12, 0)))
    idx = proxy.index(0, 0)
    img = QImage(600, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    opt = _opt(view)
    opt.rect.setHeight(delegate.sizeHint(opt, idx).height())
    delegate.paint(p, opt, idx)          # normal
    delegate.set_copied(idx)
    delegate.paint(p, opt, idx)          # copied ✓ variant
    p.end()
    assert delegate._copied is not None
    delegate.clear_copied()
    assert delegate._copied is None
