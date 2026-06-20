"""Scale-aware card tests (transparent-mode Task 1.2b).

`_CompactLayout.apply_metrics(CardMetrics(scale))` recomputes a built card's
geometry (sizes/fonts/icons + painted body radii) from a single value object,
without rebuilding the widget tree. These tests exercise the real card-build
path (a MultitoonTab) under config + keyring isolation, then:
  * assert a non-1.0 scale shrinks the portrait/control/font dimensions
    proportionally, and
  * smoke-render a single card surface offscreen at 0.5 / 1.0 / 1.75 (spec §16)
    and confirm the reported scaled sizes.

Run in isolation (never the whole tests/ dir, it hangs):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
    TTMT_CONFIG_DIR=$(mktemp -d) PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
    ./venv/bin/python -m pytest tests/test_card_scaling.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from utils.overlay.card_metrics import CardMetrics


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass

    def get_active_window(self):
        return None


def _build_tab(qapp, tmp_path, monkeypatch):
    """Build a real MultitoonTab in isolation; conftest shuts the input service
    down on teardown so the non-daemon worker thread cannot leak."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_apply_metrics_shrinks_card_proportionally(qapp, tmp_path, monkeypatch):
    """A built card recomputes its geometry from CardMetrics(0.6): the portrait
    frame, controls column, toggle buttons, KA dot, and name font all shrink to
    the value object's scaled dimensions; the structural tree is not rebuilt."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    cell = layout._cells[0]
    name_label = tab.toon_labels[0][0]

    # Baseline at the default scale 1.0.
    base = CardMetrics(1.0)
    assert cell["portrait_frame"].width() == base.portrait        # 172
    assert cell["ctrl_wrap"].maximumWidth() == base.ctrl_w        # 158
    assert tab.toon_buttons[0].width() == base.toggle_w           # 34
    assert tab.keep_alive_buttons[0].width() == base.ka_dot       # 28
    assert name_label.font().pixelSize() == round(base.font_pt(23))  # 23
    assert layout._status_host.getContentsMargins()[1] == base.status_top_margin  # 14

    # ~0.6 makes rounding differences visible (not a clean 0.5).
    m = CardMetrics(0.6)
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()

    assert cell["portrait_frame"].width() == m.portrait          # round(172*0.6)=103
    assert cell["portrait_frame"].height() == m.portrait
    assert cell["ctrl_wrap"].maximumWidth() == m.ctrl_w          # round(158*0.6)=95
    assert tab.toon_buttons[0].width() == m.toggle_w             # round(34*0.6)=20
    assert tab.toon_buttons[0].height() == m.toggle_h            # round(36*0.6)=22
    assert tab.keep_alive_buttons[0].width() == m.ka_dot         # round(28*0.6)=17
    assert name_label.font().pixelSize() == round(m.font_pt(23))  # round(13.8)=14
    assert layout._status_host.getContentsMargins()[1] == m.status_top_margin  # round(14*0.6)=8

    # Every dimension is strictly smaller than the 1.0 baseline.
    assert m.portrait < base.portrait
    assert m.ctrl_w < base.ctrl_w
    assert m.toggle_w < base.toggle_w
    assert round(m.font_pt(23)) < round(base.font_pt(23))

    # The same metrics re-applied is idempotent (no drift).
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()
    assert cell["portrait_frame"].width() == m.portrait
    assert cell["ctrl_wrap"].maximumWidth() == m.ctrl_w


@pytest.mark.parametrize("scale", [0.5, 1.0, 1.75])
def test_card_surface_renders_offscreen_at_scale(qapp, tmp_path, monkeypatch, scale):
    """A single card surface (painted body + portrait frame + emblem) renders
    offscreen at 0.5 / 1.0 / 1.75 without error and reports the scaled size."""
    from tabs.multitoon._compact_layout import _Emblem

    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    m = CardMetrics(scale)
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()

    cell = layout._cells[0]
    frame = cell["portrait_frame"]
    bg = cell["bg"]
    emblem = layout._emblem

    # Reported scaled sizes.
    assert frame.width() == m.portrait
    assert frame.height() == m.portrait
    assert emblem.width() == m.emblem + 2 * m.icon_px(_Emblem._RING_MARGIN)

    # Give the painted body a positive scaled card size so paintEvent exercises
    # the body-path radii at this scale.
    card_w = round(330 * scale)
    card_h = m.card_min_h
    bg.resize(card_w, card_h)

    # Render each surface to an offscreen ARGB image; must not raise.
    for w in (bg, frame, emblem):
        size = w.size()
        img = QImage(max(1, size.width()), max(1, size.height()), QImage.Format_ARGB32)
        img.fill(0)
        w.render(img)


def test_emblem_decorative_rings_fit_at_half_scale(qapp, tmp_path, monkeypatch):
    """At scale 0.5 the broadcast ring + armed ring (offset radius AND pen
    width) must fit inside the emblem widget so they do not clip. paintEvent
    draws each ring at `r + offset*scale` with a `pen*scale` stroke, so the
    outer painted extent is `r + offset*scale + pen*scale/2`; that must stay
    within the widget half-size (`r + scaled ring margin`). Rendering both
    decorative branches offscreen must also not raise."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    emblem = layout._emblem

    m = CardMetrics(0.5)
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()

    assert emblem._scale == m.scale  # 0.5

    half = emblem.width() / 2.0
    r = emblem._d / 2.0
    s = emblem._scale
    # Mirror paintEvent: extent = radius + offset*scale + pen_width*scale / 2.
    broadcast_extent = r + 4 * s + (8 * s) / 2.0
    armed_extent = r + 9 * s + (2 * s) / 2.0
    assert broadcast_extent <= half, (broadcast_extent, half)
    assert armed_extent <= half, (armed_extent, half)

    # Exercise BOTH decorative paint branches and render offscreen (no raise).
    emblem._broadcasting = True
    emblem._armed = True
    img = QImage(max(1, emblem.width()), max(1, emblem.height()), QImage.Format_ARGB32)
    img.fill(0)
    emblem.render(img)


def test_ka_pill_border_radius_scales(qapp, tmp_path, monkeypatch):
    """The keep-alive pill's border-radius tracks its (scaled) height so the
    capsule stays a true pill. At 1.0 the radius is exactly 19 (== 38/2,
    unchanged); at 0.6 and 1.75 it differs from 19 and equals
    round(ka_pill_h/2)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    ka_pill = layout._cells[0]["ka_pill"]

    base = CardMetrics(1.0)
    layout.apply_metrics(base)
    for _ in range(3):
        qapp.processEvents()
    assert round(base.ka_pill_h / 2) == 19
    assert "border-radius: 19px" in ka_pill.styleSheet()

    for scale in (0.6, 1.75):
        m = CardMetrics(scale)
        layout.apply_metrics(m)
        for _ in range(3):
            qapp.processEvents()
        expected = round(m.ka_pill_h / 2)
        assert expected != 19
        assert f"border-radius: {expected}px" in ka_pill.styleSheet(), ka_pill.styleSheet()


def test_emblem_rings_do_not_clip_widget_edge_at_half_scale(qapp, tmp_path, monkeypatch):
    """Behavioral PAINT guard (stronger than the formula-mirroring fit test):
    render the broadcasting + armed emblem at scale 0.5 to a widget-sized QImage
    and assert the decorative rings stay off the widget's outer 1px border. If
    paintEvent reverted to FIXED ring offsets / pen widths, the rings would clip
    the (scaled-down) widget edge and the border would no longer be transparent,
    so this fails. Also asserts the render is non-blank so it cannot pass
    vacuously. Deterministic + offscreen."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    emblem = layout._emblem

    m = CardMetrics(0.5)
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()

    # Drive BOTH decorative branches (broadcast pulse ring + armed ring) and
    # render to an image sized exactly to the widget.
    emblem._broadcasting = True
    emblem._armed = True
    w, h = emblem.width(), emblem.height()
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)  # fully transparent
    emblem.render(img)

    # Outer ~1px border must be (near-)transparent: neither ring nor disc
    # reaches it. A tiny tolerance absorbs antialiasing bleed.
    tol = 8
    border_alphas = []
    for x in range(w):
        border_alphas.append(QColor(img.pixelColor(x, 0)).alpha())
        border_alphas.append(QColor(img.pixelColor(x, h - 1)).alpha())
    for y in range(h):
        border_alphas.append(QColor(img.pixelColor(0, y)).alpha())
        border_alphas.append(QColor(img.pixelColor(w - 1, y)).alpha())
    assert max(border_alphas) <= tol, ("border not transparent", max(border_alphas))

    # Non-blank: the opaque emblem disc means many interior pixels are opaque.
    opaque = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if QColor(img.pixelColor(x, y)).alpha() > 128:
                opaque += 1
    assert opaque > 0, "render was blank"


def test_layout_spacings_and_ka_pill_margins_scale(qapp, tmp_path, monkeypatch):
    """The _CompactLayout-owned layout spacings/margins (outer cluster margins,
    card content spacing, control-column/toggle/body/stats/meta spacings) AND the
    KA pill's internal margins/spacing are scale-aware: at 1.0 they equal the
    original literals byte-for-byte; at 0.6 each equals round(base*0.6) and
    differs from the 1.0 value. Reads the ACTUAL layout objects."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    layout = tab._compact
    cell = layout._cells[0]

    def outer_margins():
        return layout._outer.getContentsMargins()

    def ka_margins():
        return cell["ka_lay"].getContentsMargins()

    base = CardMetrics(1.0)
    layout.apply_metrics(base)
    for _ in range(3):
        qapp.processEvents()

    # At 1.0: byte-for-byte equal to the original literals.
    assert outer_margins() == (8, 6, 8, 8)
    assert cell["content"].spacing() == 12
    assert cell["toggle_row"].spacing() == 9
    assert cell["ctrl_col"].spacing() == 10
    assert cell["body_row"].spacing() == 10
    assert cell["stats_row"].spacing() == 16
    assert cell["meta_col"].spacing() == 5
    assert ka_margins() == (5, 0, 11, 0)
    assert cell["ka_lay"].spacing() == 9

    # At 0.6: each equals round(base*0.6) and differs from the 1.0 value.
    m = CardMetrics(0.6)
    layout.apply_metrics(m)
    for _ in range(3):
        qapp.processEvents()

    assert outer_margins() == (
        m.icon_px(8), m.icon_px(6), m.icon_px(8), m.icon_px(8),
    )
    assert outer_margins() != (8, 6, 8, 8)
    assert cell["content"].spacing() == m.icon_px(12) != 12
    assert cell["toggle_row"].spacing() == m.icon_px(9) != 9
    assert cell["ctrl_col"].spacing() == m.icon_px(10) != 10
    assert cell["body_row"].spacing() == m.icon_px(10) != 10
    assert cell["stats_row"].spacing() == m.icon_px(16) != 16
    assert cell["meta_col"].spacing() == m.icon_px(5) != 5
    assert ka_margins() == (m.icon_px(5), 0, m.icon_px(11), 0)
    assert ka_margins() != (5, 0, 11, 0)
    assert cell["ka_lay"].spacing() == m.icon_px(9) != 9

    # Back to 1.0: restored byte-for-byte.
    layout.apply_metrics(base)
    for _ in range(3):
        qapp.processEvents()
    assert outer_margins() == (8, 6, 8, 8)
    assert cell["content"].spacing() == 12
    assert ka_margins() == (5, 0, 11, 0)
    assert cell["ka_lay"].spacing() == 9


def test_glow_cache_is_bounded(qapp, tmp_path, monkeypatch):
    """The _GlowLayer pixmap cache is an LRU bounded to _GLOW_CACHE_MAX entries:
    churning many distinct (size, accent, blur) specs must never grow it past the
    cap (so repeated rescale / theme / accent changes can't accumulate large
    blurred QPixmaps without limit)."""
    from tabs.multitoon._compact_layout import _GlowLayer, _GLOW_CACHE_MAX

    glow = _GlowLayer()
    accents = ["#ff0000", "#00ff00", "#0000ff", "#ffaa00", "#00ffaa", "#aa00ff"]
    # Each iteration uses a unique width -> a unique cache key, so the cache
    # fills well past the cap and must then evict oldest entries.
    for n in range(60):
        glow.set_blur(10 + (n % 15))
        glow.set_cards([{
            "x": 0, "y": 0,
            "w": 120 + n * 8, "h": 130 + (n % 7) * 8,
            "cutout": "br", "accent": accents[n % len(accents)],
        }])
        assert len(glow._cache) <= _GLOW_CACHE_MAX

    assert len(glow._cache) <= _GLOW_CACHE_MAX
    # And we actually exceeded the cap's worth of distinct keys (so the bound
    # was genuinely exercised, not trivially satisfied).
    assert len(glow._cache) == _GLOW_CACHE_MAX
