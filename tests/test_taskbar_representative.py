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


def test_prepare_initial_state_requests_below_and_clickthrough_no_opacity(qapp):
    """Pre-map: keep-below + empty input shape. NO opacity write - the rep maps
    ALIGNED under the cluster (invisible by construction); opacity is reserved
    for set_blanked()."""
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    rep.prepare_initial_state()
    assert backend.rep_state == [rep]
    assert backend.opacities == []           # opacity is set_blanked's job only
    assert len(backend.input_regions) == 1
    win, region = backend.input_regions[0]
    assert win is rep
    assert region.isEmpty()                  # EMPTY input shape = click-through
    rep.deleteLater()


def test_set_blanked_toggles_window_opacity_idempotently(qapp):
    backend = _RecordingBackend()
    rep = _make_rep(backend=backend)
    assert rep.is_blanked() is False
    rep.set_blanked(True)
    rep.set_blanked(True)                    # idempotent: no second write
    assert rep.is_blanked() is True
    assert backend.opacities == [(rep, 0.0)]
    rep.set_blanked(False)
    assert rep.is_blanked() is False
    assert backend.opacities == [(rep, 0.0), (rep, 1.0)]
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
