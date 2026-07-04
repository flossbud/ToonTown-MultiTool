import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="run under QT_QPA_PLATFORM=offscreen",
)


@pytest.fixture(autouse=True)
def _force_radial_anim_enabled(monkeypatch):
    # These tests assert animated / deferred behavior, so isolate them from an
    # ambient TTMT_NO_RADIAL_ANIM in the dev shell. The kill-switch test sets it
    # back via its own monkeypatch.setenv after this autouse fixture runs.
    # Also pin reduce-motion OFF: _anim_enabled now consults is_reduced(), which
    # would otherwise fall back to OS detection (animations-off CI -> snap fails).
    monkeypatch.delenv("TTMT_NO_RADIAL_ANIM", raising=False)
    monkeypatch.setattr("utils.motion.is_reduced", lambda: False)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_main_ring_emits_action_intents_on_hit():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    fired = []
    w.accounts_requested.connect(lambda: fired.append("accounts"))
    w.home_requested.connect(lambda: fired.append("home"))
    w.settings_requested.connect(lambda: fired.append("settings"))
    w.hide_cards_requested.connect(lambda: fired.append("hide"))
    w.exit_requested.connect(lambda: fired.append("exit"))
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    # action spokes fire immediately; "close" is deferred (covered separately)
    for key in ("accounts", "home", "settings", "hide", "exit"):
        cx, cy, r = w.circle_geometry("main", key)
        w.activate_at(cx, cy)
    assert fired == ["accounts", "home", "settings", "hide", "exit"]
    assert closed == []          # no close spoke was hit


def test_click_outside_any_circle_does_not_emit():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    fired = []
    w.close_requested.connect(lambda: fired.append("x"))
    w.activate_at(2, 2)
    assert fired == []


def test_interactive_path_covers_spokes_only():
    """interactive_path() - the radial window's X11 input shape - contains every
    visible spoke circle (with the hover-lift padding) and NOTHING else: not the
    widget center (the emblem shows through there) and not the corners, so game
    UI beneath the invisible canvas stays clickable while the ring is open.
    Swapping to the accounts sub-ring re-announces via state_changed (the
    controller's input-reshape hook) and the path follows the new spoke set."""
    _app()
    from PySide6.QtCore import QPointF
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160)
    w.resize(640, 640)
    path = w.interactive_path()
    for (_state, _key, cx, cy, r) in w._visible_circles():
        assert path.contains(QPointF(cx, cy))              # spoke center
        assert path.contains(QPointF(cx + r, cy))          # spoke edge (padded)
    assert not path.contains(QPointF(320, 320))            # emblem center: excluded
    assert not path.contains(QPointF(5, 5))                # canvas corner: excluded

    fired = []
    w.state_changed.connect(lambda: fired.append(1))
    w.set_accounts([RingAccount("a1", "ttr", "L1", None, "", False)])
    assert fired == [1]                                    # swap announced
    path2 = w.interactive_path()
    for (_state, _key, cx, cy, r) in w._visible_circles():
        assert path2.contains(QPointF(cx, cy))             # accounts spokes covered


def test_paint_does_not_crash():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    pm = QPixmap(400, 400)
    p = QPainter(pm)
    w.render(p, QPoint(0, 0))   # exercises paintEvent paths without a live event loop
    p.end()


def test_accounts_state_lays_out_n_circles_and_emits_account_id():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    accts = [RingAccount(f"id{i}", "ttr", f"L{i}", f"T{i}", "", True, False) for i in range(8)]
    w.set_accounts(accts)
    assert w.state == "accounts"
    clicked = []
    w.account_clicked.connect(clicked.append)
    for i in range(8):
        cx, cy, r = w.circle_geometry("accounts", i)
        w.activate_at(cx, cy)
    assert clicked == [f"id{i}" for i in range(8)]


def test_back_returns_to_main_state():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False)])
    back = []
    w.back_requested.connect(lambda: back.append(1))
    cx, cy, r = w.circle_geometry("accounts", "back")
    w.activate_at(cx, cy)
    assert back == [1] and w.state == "main"


def _click_account(w, i):
    cx, cy, r = w.circle_geometry("accounts", i)
    w.activate_at(cx, cy)


def test_auto_close_only_after_last_account_launched():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False),
                    RingAccount("b", "ttr", "L", "T", "", True, False)])
    w._advance(10_000)
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    _click_account(w, 0)
    assert closed == []          # one still un-launched -> stay open
    _click_account(w, 1)
    assert closed == []          # all launched -> close BEGINS (deferred)
    w._advance(10_000)
    assert closed == [1]


def test_already_running_accounts_count_toward_all_launched():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False),
                    RingAccount("b", "ttr", "L", "T", "", True, True)])
    w._advance(10_000)
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    _click_account(w, 0)
    assert closed == []
    w._advance(10_000)
    assert closed == [1]


def test_opening_all_running_ring_does_not_auto_close():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    # All already running: opening must NOT auto-close (no click happened).
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, True),
                    RingAccount("b", "ttr", "L", "T", "", True, True)])
    assert closed == []


def test_accounts_paint_does_not_crash():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", None, "", True, False),   # placeholder
                    RingAccount("b", "cc", "L2", "Toon", "", True, True)])
    w._hover = ("accounts", 0)   # exercise hover-label path
    pm = QPixmap(500, 500); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()


def test_reveal_order_is_left_to_right():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    order = w.reveal_order("main")
    xs = [w.circle_geometry("main", k)[0] for k in order]
    assert xs == sorted(xs)


def test_esc_begins_deferred_close():
    _app()
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert fired == []
    w._advance(10_000)
    assert fired == [1]


def test_idle_timeout_is_15s():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160)
    assert w.idle_timeout_ms() == 15000


def test_idle_timer_begins_deferred_close():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    assert w._idle_timer.isSingleShot()
    assert w._idle_timer.interval() == 15000
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w._idle_timer.timeout.emit()
    assert fired == []
    w._advance(10_000)
    assert fired == [1]


def test_running_account_paints_status_dot():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "Toon", "", True, True)])
    # settle the entrance so the account paints at full size
    w._advance(10_000)
    img = QImage(500, 500, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); w.render(p, QPoint(0, 0)); p.end()
    # scan for a strongly-green pixel (the status dot)
    found = False
    for yy in range(0, 500, 2):
        for xx in range(0, 500, 2):
            c = img.pixelColor(xx, yy)
            if c.green() > 170 and c.green() - c.red() > 80 and c.green() - c.blue() > 60:
                found = True; break
        if found: break
    assert found, "running status dot (green) not painted"


def test_reveal_animates_then_completes():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    w._advance(0)                                # mid-reveal: must not crash
    pm = QPixmap(400, 400); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()
    w._advance(10_000)                           # settle
    assert w._appear_active is False
    pm2 = QPixmap(400, 400); p2 = QPainter(pm2); w.render(p2, QPoint(0, 0)); p2.end()


def test_default_variant_is_transparent_six_spokes():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    assert sorted(w.reveal_order("main")) == sorted(
        ["accounts", "home", "settings", "hide", "close", "exit"])


def test_windowed_variant_has_three_spokes():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    assert sorted(w.reveal_order("main")) == sorted(["accounts", "transparent", "close"])


def test_windowed_variant_emits_per_spoke():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    w.start_reveal(); w._advance(10_000)
    fired = []
    w.accounts_requested.connect(lambda: fired.append("accounts"))
    w.transparent_requested.connect(lambda: fired.append("transparent"))
    closed = []
    w.close_requested.connect(lambda: closed.append(1))
    # action spokes fire immediately; "close" is deferred (covered separately)
    for key in ("accounts", "transparent"):
        cx, cy, r = w.circle_geometry("main", key)
        w.activate_at(cx, cy)
    assert fired == ["accounts", "transparent"]
    assert closed == []          # no close spoke was hit


def test_hide_spoke_is_bottom_center():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    cx, cy, r = w.circle_geometry("main", "hide")
    # bottom-center: x == widget center x, y below center
    assert round(cx, 3) == round(w.width() / 2.0, 3)
    assert cy > w.height() / 2.0


def test_windowed_variant_has_no_hide_spoke():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    assert "hide" not in w.reveal_order("main")


def test_hide_spoke_label_and_glyph_follow_cards_hidden_state():
    """The Hide-Cards spoke is a TOGGLE display: label "Hide Cards" (slashed
    eye) while the cards are visible, "Show Cards" (open eye) once the host
    feeds set_cards_hidden(True). Both glyph variants must paint. The label is
    a BOTTOM label (renders below the spoke, like Back/Exit)."""
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import (RadialMenuWidget, _MAIN_BOTTOM_KEYS,
                                           _MAIN_LABELS, _eye)
    assert _MAIN_LABELS["hide"] == "Hide Cards"
    assert "hide" in _MAIN_BOTTOM_KEYS
    assert callable(_eye)
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    w._hover = ("main", "hide")                 # exercise hover label + glyph
    assert w._label_for("hide") == "Hide Cards"
    pm = QPixmap(400, 400); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()

    w.set_cards_hidden(True)                    # host says: cards now hidden

    assert w._label_for("hide") == "Show Cards"
    pm2 = QPixmap(400, 400); p2 = QPainter(pm2); w.render(p2, QPoint(0, 0)); p2.end()
    # set_cards_hidden is idempotent (no crash / state flip on a repeat call)
    w.set_cards_hidden(True)
    assert w._label_for("hide") == "Show Cards"
    w.set_cards_hidden(False)
    assert w._label_for("hide") == "Hide Cards"


def test_windowed_transparent_spoke_is_top_center():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    cx, cy, r = w.circle_geometry("main", "transparent")
    # top-center: x == widget center x, y above center
    assert round(cx, 3) == round(w.width() / 2.0, 3)
    assert cy < w.height() / 2.0


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an active overlay + X display")
def test_controller_radial_open_close_smoke():
    # Live behavior (the controller hosting a click-accepting radial surface) is
    # validated manually on the packaged build; real X11 shaped surfaces are not
    # reliable headless. This documents the gap.
    pass


def test_windowed_paint_does_not_crash_and_label_present():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from utils.overlay.radial_menu import RadialMenuWidget, _MAIN_LABELS, _overlay_cards
    assert _MAIN_LABELS["transparent"] == "Float"
    assert callable(_overlay_cards)
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    w._hover = ("main", "transparent")          # exercise hover label + glyph
    pm = QPixmap(500, 500); p = QPainter(pm); w.render(p, QPoint(0, 0)); p.end()


def test_press_depresses_then_springs_back_and_activates():
    _app()
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    cx, cy, r = w.circle_geometry("main", "settings")
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(cx, cy),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(press)
    assert w._press_hit == ("main", "settings")
    for _ in range(6):                       # depress while held
        w._advance(0)
    assert w._press_scale_val < 1.0
    fired = []
    w.settings_requested.connect(lambda: fired.append(1))
    rel = QMouseEvent(QEvent.MouseButtonRelease, QPointF(cx, cy),
                      Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    w.mouseReleaseEvent(rel)
    assert fired == [1]                      # activation still on release
    for _ in range(60):                      # spring-back completes
        w._advance(0)
    assert w._press_hit is None
    assert w._press_scale_val == 1.0


def test_press_is_still_accepted_not_propagated():
    _app()
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(2, 2),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ev.setAccepted(False)
    w.mousePressEvent(ev)
    assert ev.isAccepted()                   # consumed even when no spoke is hit


def test_windowed_variant_accounts_subring_and_back():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.radial_menu_model import RingAccount
    w = RadialMenuWidget(emblem_diameter=160, variant="windowed"); w.resize(500, 500)
    w.set_accounts([RingAccount("a", "ttr", "L", "T", "", True, False)])
    assert w.state == "accounts"
    back = []
    w.back_requested.connect(lambda: back.append(1))
    cx, cy, r = w.circle_geometry("accounts", "back")
    w.activate_at(cx, cy)
    assert back == [1] and w.state == "main"
    # Back returns to the WINDOWED 3-spoke ring, not the transparent 5-spoke one.
    assert sorted(w.reveal_order("main")) == sorted(["accounts", "transparent", "close"])


def test_easing_and_interpolation_helpers():
    from utils.overlay.radial_menu import (
        _clamp01, _lerp, _ease_out, _ease_in, _ease_spring)
    # endpoints
    assert _ease_out(0.0) == 0.0 and abs(_ease_out(1.0) - 1.0) < 1e-9
    assert _ease_in(0.0) == 0.0 and abs(_ease_in(1.0) - 1.0) < 1e-9
    assert abs(_ease_spring(0.0)) < 1e-9 and abs(_ease_spring(1.0) - 1.0) < 1e-9
    # ease_out decelerates (ahead of linear), ease_in accelerates (behind)
    assert _ease_out(0.5) > 0.5
    assert _ease_in(0.5) < 0.5
    # spring overshoots above 1.0 somewhere in (0,1)
    assert max(_ease_spring(i / 100.0) for i in range(101)) > 1.0
    # clamp + lerp
    assert _clamp01(-3.0) == 0.0 and _clamp01(2.0) == 1.0 and _clamp01(0.4) == 0.4
    assert _lerp(10.0, 20.0, 0.5) == 15.0
    assert _lerp(10.0, 20.0, 0.0) == 10.0 and _lerp(10.0, 20.0, 1.0) == 20.0


def test_drop_shadow_darkens_below_disc():
    _app()
    from PySide6.QtGui import QImage, QPainter, QColor
    from utils.overlay.radial_menu import _drop_shadow
    img = QImage(220, 240, QImage.Format_ARGB32)
    img.fill(QColor(60, 60, 60))                 # opaque mid-grey backdrop
    p = QPainter(img)
    _drop_shadow(p, 110, 100, 55, 1.0)
    p.end()
    below = img.pixelColor(110, 165)             # under the disc center
    assert below.red() < 55                      # darkened by the shadow


def test_refined_painters_paint_without_crash():
    _app()
    from PySide6.QtGui import QImage, QPainter
    from utils.overlay.radial_menu import _disc, _focus_glow
    img = QImage(220, 220, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img)
    _focus_glow(p, 110, 110, 50, 0.8)            # azure hover halo
    _focus_glow(p, 110, 110, 50, 0.8, danger=True)  # red variant
    _disc(p, 110, 110, 50, hot=True, danger=False)
    _disc(p, 110, 110, 50, hot=False, danger=True)
    p.end()


def test_shadow_is_built_and_matches_widget_size():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtCore import QPoint
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget(); w.resize(400, 400)
    w.progress = 1.0
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.render(pm, QPoint(0, 0))
    assert w._shadow is not None
    assert abs(w._shadow.deviceIndependentSize().width() - 400.0) < 0.5
    w.resize(500, 500)
    pm = QPixmap(w.size()); pm.fill(QColor(0, 0, 0, 0))
    w.render(pm, QPoint(0, 0))
    assert abs(w._shadow.deviceIndependentSize().width() - 500.0) < 0.5


def test_radial_menu_widget_no_longer_owns_the_dim():
    """The dim moved to its own layer (RadialDimWidget); the menu paints only the
    spoke buttons so the dim can sit behind the emblem."""
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160)
    assert not hasattr(w, "_ensure_vignette")
    assert not hasattr(w, "_vignette")


def test_radial_dim_widget_is_click_through():
    """The dim is purely decorative and must never grab input."""
    from PySide6.QtCore import Qt
    _app()
    from utils.overlay.radial_menu import RadialDimWidget
    w = RadialDimWidget()
    assert w.testAttribute(Qt.WA_TransparentForMouseEvents)


def test_entrance_starts_at_center_and_settles_at_slot():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    w._advance(0)
    assert w._circle_vis("home") < 0.05          # t=0: collapsed at the emblem
    w._advance(10_000)
    assert w._circle_vis("home") == 1.0          # settled at its slot
    assert w._appear_active is False


def test_close_is_deferred_until_flyback_completes():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    cx, cy, r = w.circle_geometry("main", "close")
    w.activate_at(cx, cy)
    assert fired == []                           # animating, not yet closed
    assert w._closing is True
    w._advance(10_000)
    assert fired == [1]                          # fires once on completion
    w._advance(10_000)
    assert fired == [1]                          # idempotent - no second emit


def test_activation_ignored_while_closing():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    w._begin_close()
    fired = []
    w.accounts_requested.connect(lambda: fired.append(1))
    cx, cy, r = w.circle_geometry("main", "accounts")
    w.activate_at(cx, cy)
    assert fired == []


def test_kill_switch_makes_appear_and_close_synchronous(monkeypatch):
    _app()
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    assert w._appear_active is False
    assert w._circle_vis("home") == 1.0          # instant, fully visible
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w._begin_close()
    assert fired == [1]                           # synchronous close


def test_reduce_motion_snaps_the_ring(monkeypatch):
    monkeypatch.delenv("TTMT_NO_RADIAL_ANIM", raising=False)
    monkeypatch.setattr("utils.motion.is_reduced", lambda: True)
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    assert w._anim_enabled is False
    w.start_reveal()
    # snap path: no active appear animation, everything fully shown
    assert w._appear_active is False
    assert all(v == 1.0 for v in w._appear_progress.values())


def test_hover_progress_eases_toward_hovered_spoke():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)          # settle entrance
    w._hover = ("main", "settings")
    for _ in range(40):                            # converge
        w._advance(20_000)
    assert w._hover_progress["settings"] == 1.0
    assert all(w._hover_progress[k] == 0.0
               for k in w.reveal_order("main") if k != "settings")
    w._hover = None
    for _ in range(40):
        w._advance(20_000)
    assert all(v == 0.0 for v in w._hover_progress.values())


def test_close_mid_entrance_flies_back_from_current_position():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    w._advance(100)                                  # partway through the 360ms entrance
    mid = {k: w._circle_vis(k) for k in w.reveal_order("main")}
    assert any(0.0 < v < 1.0 for v in mid.values())  # genuinely mid-flight
    w._begin_close()
    w._advance(0)                                    # first close frame
    # must NOT snap to the full slot first: each circle starts the fly-back from
    # where it currently was (<= its mid-entrance vis), never jumping outward.
    for k, v in mid.items():
        assert w._circle_vis(k) <= v + 1e-6
    w._advance(10_000)
    assert all(w._circle_vis(k) == 0.0 for k in mid)  # fully flown back


def test_kill_switch_begin_close_is_idempotent(monkeypatch):
    _app()
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal()
    fired = []
    w.close_requested.connect(lambda: fired.append(1))
    w._begin_close()
    w._begin_close()                                 # second call must NOT re-emit
    assert fired == [1]


def test_emblem_center_click_closes_menu():
    # Clicking the emblem (which shows through the ring's transparent center)
    # toggles the open menu shut - the inverse of the click that opened it.
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.start_reveal(); w._advance(10_000)             # settle so spokes sit at slots
    closed = []
    w.closing.connect(lambda: closed.append(1))
    cx, cy = w._center()
    w.activate_at(cx, cy)                            # dead center == the emblem
    assert closed == [1]


def test_outer_gap_click_does_not_close():
    # A click that misses every spoke AND the emblem (a canvas corner) is a
    # no-op, not a close - only the emblem closes.
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(500, 500)
    w.start_reveal(); w._advance(10_000)
    closed = []
    w.closing.connect(lambda: closed.append(1))
    w.activate_at(5, 5)                              # corner: no spoke, not emblem
    assert closed == []


# --- set_emblem_diameter (live re-size to track the emblem) -------------------

def test_set_emblem_diameter_updates_ring_geometry():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    old_ring, old_sat = w._ring, w._sat_r
    w.set_emblem_diameter(320)
    assert w._emblem_dia == 320.0
    assert w._sat_r == 320 * 0.40 / 2.0
    assert w._ring == 320 / 2.0 + 16.0 + w._sat_r
    assert w._ring > old_ring and w._sat_r > old_sat


def test_set_emblem_diameter_moves_spokes_outward():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    center = w._center()
    cx0, cy0, r0 = w.circle_geometry("main", "home")
    d0 = ((cx0 - center[0]) ** 2 + (cy0 - center[1]) ** 2) ** 0.5
    w.set_emblem_diameter(320)
    cx1, cy1, r1 = w.circle_geometry("main", "home")
    d1 = ((cx1 - center[0]) ** 2 + (cy1 - center[1]) ** 2) ** 0.5
    assert d1 > d0          # spoke pushed further from the center
    assert r1 > r0          # satellite grew


def test_set_emblem_diameter_noop_for_same_value():
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    before = (w._emblem_dia, w._ring, w._sat_r)
    w.set_emblem_diameter(160)      # unchanged
    assert (w._emblem_dia, w._ring, w._sat_r) == before


# --- darwin hover-poll (cocoa tracking is active-app-only) --------------------
# While a game is frontmost, cocoa never delivers mouseMoveEvent to the
# nonactivating radial panel, so hover (labels, lift, glow) was dead until a
# click - which on an account portrait LAUNCHES the account (user report
# 2026-07-04). A 50ms global-cursor poll mirrors the mouseMoveEvent hover
# transition on darwin; X11/win32 keep the pure event path.

def _darwin_ring(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "darwin")
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    return w


def test_darwin_hover_poll_created_and_show_hide_gated(monkeypatch):
    _app()
    w = _darwin_ring(monkeypatch)
    assert w._hover_poll is not None
    w.show()
    assert w._hover_poll.isActive() is True     # polling only while shown
    w.hide()
    assert w._hover_poll.isActive() is False


def test_non_darwin_has_no_hover_poll(monkeypatch):
    _app()
    import sys
    monkeypatch.setattr(sys, "platform", "linux")
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160)
    assert w._hover_poll is None                # event path untouched off-darwin


def test_darwin_poll_mirrors_hover_transition_and_rearms_idle(monkeypatch):
    _app()
    from PySide6.QtCore import QPoint
    w = _darwin_ring(monkeypatch)
    cx, cy, _r = w.circle_geometry("main", "settings")

    # Cursor over the settings spoke: hover set WITHOUT any mouseMoveEvent,
    # and presence over a spoke re-arms the idle countdown (a cursor resting
    # on a portrait to read its label must never idle-close the ring).
    monkeypatch.setattr(w, "mapFromGlobal", lambda _p: QPoint(int(cx), int(cy)))
    w._idle_timer.stop()
    w._poll_hover()
    assert w._hover == ("main", "settings")
    assert w._idle_timer.isActive() is True

    # Cursor far outside the widget: hover clears on the next tick.
    monkeypatch.setattr(w, "mapFromGlobal", lambda _p: QPoint(-500, -500))
    w._poll_hover()
    assert w._hover is None


def test_spoke_at_matches_real_hit_test_and_guards_closing():
    """spoke_at is the ghost-click resolver's public hit test: same result as
    the real-click _hit at a spoke center, None off-spoke, and None while the
    close fly-back plays (matching activate_at's guard - a late ghost press
    must not be silently consumed)."""
    _app()
    from utils.overlay.radial_menu import RadialMenuWidget
    w = RadialMenuWidget(emblem_diameter=160); w.resize(400, 400)
    w.start_reveal(); w._advance(10_000)
    cx, cy, _r = w.circle_geometry("main", "settings")
    assert w.spoke_at(cx, cy) == ("main", "settings")
    assert w.spoke_at(2, 2) is None
    w._closing = True
    assert w.spoke_at(cx, cy) is None
