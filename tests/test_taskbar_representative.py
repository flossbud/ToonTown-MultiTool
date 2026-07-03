"""TaskbarRepresentative: the float-UI taskbar/Alt-Tab stand-in (offscreen)."""
from utils.overlay.backend import NoOpOverlayBackend


def test_noop_backend_accepts_representative_hint_calls():
    """The protocol additions must exist on the NoOp base (stub backends in
    other suites inherit them) and never raise."""
    b = NoOpOverlayBackend()
    b.set_rep_initial_state(object())
    b.set_window_opacity(object(), 0.0)


from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap

from utils.build_flavor import window_title
from utils.overlay.taskbar_representative import TaskbarRepresentative


class _RecordingBackend(NoOpOverlayBackend):
    def __init__(self):
        self.rep_state: list = []
        self.opacities: list = []
        self.input_regions: list = []

    def set_rep_initial_state(self, window):
        self.rep_state.append(window)

    def set_window_opacity(self, window, opacity):
        self.opacities.append((window, float(opacity)))

    def apply_input_region(self, window, region):
        self.input_regions.append((window, region))


class _FakeCloseEvent:
    def __init__(self, spontaneous):
        self._spont = spontaneous
        self.ignored = False
        self.accepted = False

    def spontaneous(self):
        return self._spont

    def ignore(self):
        self.ignored = True

    def accept(self):
        self.accepted = True


def _make_rep(backend=None, on_close=None, on_tick=None):
    return TaskbarRepresentative(
        on_close_requested=on_close, on_tick=on_tick,
        backend=backend if backend is not None else NoOpOverlayBackend())


def test_flags_listed_focusable_and_translucent(qapp):
    """Listing contract: a plain frameless top-level that ACCEPTS focus (KWin's
    TabBox skips focus-refusing windows) and does not activate on map (the game
    keeps focus at float enter). Translucent: the mirror's transparent pixels
    must stay transparent on screen (aligned-mirror invariant). App title so
    the entry reads as the app."""
    rep = _make_rep()
    assert rep.windowFlags() & Qt.FramelessWindowHint
    assert not (rep.windowFlags() & Qt.WindowDoesNotAcceptFocus)
    assert rep.testAttribute(Qt.WA_ShowWithoutActivating)
    assert rep.testAttribute(Qt.WA_TranslucentBackground)
    assert rep.windowTitle() == window_title()
    rep.deleteLater()


def test_prepare_initial_state_requests_below_clickthrough_and_opacity_stage(qapp):
    """Pre-map: keep-below + empty input shape + OPACITY 0. A mapped window
    with no buffer composites as an opaque black rect on KWin/XWayland, and at
    a startup float launch the first paint can be seconds after the map - so
    the rep maps opacity-staged; the first real paint lifts the stage."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    rep.prepare_initial_state()
    assert backend.rep_state == [rep]
    assert backend.opacities == [(rep, 0.0)]   # staged until first paint
    assert len(backend.input_regions) == 1
    win, region = backend.input_regions[0]
    assert win is rep
    assert region.isEmpty()                  # EMPTY input shape = click-through
    rep.deleteLater()


def test_set_blanked_toggles_window_opacity_idempotently(qapp):
    """Blank writes opacity 0 immediately; UNBLANK never writes directly -
    it stages through a paint pass (see set_blanked's race rationale), so
    the opacity-1 write only lands one loop turn after a real paint."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    assert rep.is_blanked() is False
    rep.set_blanked(True)
    rep.set_blanked(True)                    # idempotent: no second write
    assert rep.is_blanked() is True
    assert backend.opacities == [(rep, 0.0)]
    rep.set_blanked(False)
    assert rep.is_blanked() is False
    assert backend.opacities == [(rep, 0.0)]   # staged: no direct 1.0 write
    rep.resize(60, 40)
    rep.show()                                 # offscreen: paints need a shown widget
    rep.repaint()                              # deterministic paint pass
    for _ in range(10):                        # zero-timer fires next turn
        qapp.processEvents()
        if (rep, 1.0) in backend.opacities:
            break
    assert backend.opacities == [(rep, 0.0), (rep, 1.0)]
    rep.deleteLater()


def test_blank_during_pending_unblank_wins(qapp):
    """A blank that engages while an unblank is staged cancels the pending
    lift: opacity must never bounce to 1 under an active blank."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    rep.set_blanked(True)
    rep.set_blanked(False)                   # staged...
    rep.set_blanked(True)                    # ...but a blank re-engages
    rep.resize(60, 40)
    rep.show()
    rep.repaint()
    for _ in range(10):
        qapp.processEvents()
    assert (rep, 1.0) not in backend.opacities
    assert backend.opacities[-1] == (rep, 0.0)
    rep.deleteLater()


def test_unblank_after_resize_paints_before_opacity(qapp):
    """The settle sequence (resize + unblank in the same instant) must emit
    the paint for the NEW size before the opacity-1 write - the ordering
    that prevents the settle-time flicker at the emblem."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    rep.set_blanked(True)
    events = []
    backend.set_window_opacity = lambda w, o: events.append(("opacity", float(o)))
    orig_paint = rep.paintEvent
    def paint_spy(ev):
        events.append(("paint", rep.width(), rep.height()))
        orig_paint(ev)
    rep.paintEvent = paint_spy
    pm = QPixmap(250, 250)
    pm.fill(QColor("#123456"))
    rep.set_mirror(pm)                       # resize 250x250 while blanked
    rep.show()                               # offscreen: paints need a shown widget
    rep.set_blanked(False)                   # staged unblank
    rep.repaint()
    for _ in range(10):
        qapp.processEvents()
        if ("opacity", 1.0) in events:
            break
    assert ("opacity", 1.0) in events
    lift = events.index(("opacity", 1.0))
    paints = [e for e in events[:lift] if e[0] == "paint"]
    assert paints and paints[-1][1:] == (250, 250)   # new-size paint precedes 1.0
    rep.deleteLater()


def test_set_mirror_resizes_and_paints(qapp):
    rep = _make_rep()
    pm = QPixmap(120, 80)
    pm.fill(QColor("#ff00aa"))
    rep.set_mirror(pm)
    assert rep.size() == QSize(120, 80)
    img = QImage(rep.size(), QImage.Format_ARGB32)
    img.fill(0)
    rep.render(img)
    assert img.pixelColor(60, 40) == QColor("#ff00aa")
    rep.deleteLater()


def test_spontaneous_close_is_refused_and_requests_quit(qapp):
    """Taskbar Close / preview X = quit the app: the close itself is refused
    (the controller owns this window's lifecycle) and the quit callback fires
    DEFERRED (never re-enter the WM close handshake)."""
    fired: list = []
    rep = _make_rep(on_close=lambda: fired.append(1))
    ev = _FakeCloseEvent(spontaneous=True)
    rep.closeEvent(ev)
    assert ev.ignored and not ev.accepted
    for _ in range(3):
        qapp.processEvents()                 # run the singleShot(0) callback
    assert fired == [1]
    rep.deleteLater()


def test_programmatic_close_proceeds_without_quit_request(qapp):
    fired: list = []
    rep = _make_rep(on_close=lambda: fired.append(1))
    ev = _FakeCloseEvent(spontaneous=False)
    rep.closeEvent(ev)
    assert ev.accepted and not ev.ignored
    for _ in range(3):
        qapp.processEvents()
    assert fired == []
    rep.deleteLater()


def test_minimize_is_bounced(qapp):
    """A minimized representative would freeze into a stale snapshot (probe C:
    the minimize cache is the composited image): the state change must bounce
    straight back to normal."""
    rep = _make_rep()
    rep.show()
    rep.setWindowState(rep.windowState() | Qt.WindowMinimized)
    for _ in range(3):
        qapp.processEvents()                 # run the deferred showNormal
    assert not rep.isMinimized()
    rep.hide()
    rep.deleteLater()


def test_tick_runs_only_while_shown(qapp):
    ticks: list = []
    rep = _make_rep(on_tick=lambda: ticks.append(1))
    assert not rep._tick.isActive()
    rep.show()
    assert rep._tick.isActive()
    rep._fire_tick()
    assert ticks == [1]
    rep.hide()
    assert not rep._tick.isActive()
    rep.deleteLater()


def test_first_paint_lifts_opacity_stage_repaint_before_opacity(qapp):
    """After the first real paint, the pre-map opacity stage is lifted one
    loop turn later: repaint FIRST (current buffer), THEN the 1.0 write - the
    anti-stale-frame ordering."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    events: list = []
    backend.set_window_opacity = lambda w, o: events.append(("opacity", float(o)))
    orig_repaint = rep.repaint
    rep.repaint = lambda: (events.append(("repaint",)), orig_repaint())[1]

    rep.prepare_initial_state()
    assert events == [("opacity", 0.0)]
    pm = QPixmap(QSize(40, 30))
    pm.fill(QColor("black"))
    rep.set_mirror(pm)
    rep.show()
    rep.repaint()                            # deterministic first paint
    for _ in range(10):                      # zero-timer fires next loop pass
        qapp.processEvents()
        if ("opacity", 1.0) in events:
            break
    assert events[-1] == ("opacity", 1.0)
    assert ("repaint",) in events[:-1]       # repaint preceded the 1.0 write
    assert events.count(("opacity", 1.0)) == 1
    rep.hide()
    rep.deleteLater()


def test_first_paint_lift_defers_to_engaged_blank(qapp):
    """If a blank engages between the first paint and the lift, the lift must
    NOT write opacity 1 - blanking owns opacity until its own unblank."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    rep.prepare_initial_state()
    pm = QPixmap(QSize(40, 30))
    pm.fill(QColor("black"))
    rep.set_mirror(pm)
    rep.show()
    rep.repaint()                            # first paint schedules the lift
    rep.set_blanked(True)                    # blank engages BEFORE the lift runs
    for _ in range(10):
        qapp.processEvents()
    assert (rep, 1.0) not in backend.opacities
    assert rep.is_blanked() is True
    rep.hide()
    rep.deleteLater()
