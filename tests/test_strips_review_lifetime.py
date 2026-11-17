"""A standalone strip controller releases its own inbound connections."""
import gc
import weakref
import threading
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from services.toon_session_fake import FakeToonSession, DEMO_KEYSET_IDS
from tests.test_strips_controller import Backend, Keymaps, Launcher, Settings, Strategy, settle
from utils.strips.controller import StripController
from utils.strips.follow import StripFollower


class PointerSource(QObject):
    ghost_pointer_event = Signal(object)


class Looks:
    def get(self, *_):
        return {}


def drain(qapp):
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()
        gc.collect()


def construct(session, keymaps, settings, launcher, monkeypatch):
    monkeypatch.setattr('utils.strips.follow.pick_attach_strategy', Strategy)
    monkeypatch.setattr('utils.strips.follow.get_overlay_backend', Backend)
    monkeypatch.setattr('utils.strips.follow._platform_geometry', lambda _: (100, 50, 800, 600))
    controller = StripController(session, keymap_manager=keymaps,
                                 settings_manager=settings, launcher=launcher)
    controller.start()
    controller.follower.tracker.stop()
    controller.follower.tracker.sample_now()
    controller.follower.tracker.sample_now()
    settle()
    return controller


@pytest.mark.parametrize('portraits', [False, True])
def test_shutdown_allows_collection_while_external_sources_stay_alive(qapp, monkeypatch, portraits, render_cache):
    source = PointerSource()
    monkeypatch.setattr(FakeToonSession, 'click_sync_service', property(lambda _: source))
    if portraits:
        monkeypatch.setattr(FakeToonSession, 'customizations', property(lambda _: Looks()))
    session = FakeToonSession.demo(window_ids=['101','102','103','104'])
    if portraits:
        session.update_toon('101', dna='7401')  # actually connect the shared render signals
    keymaps, settings, launcher = Keymaps(), Settings(), Launcher()
    controller = construct(session, keymaps, settings, launcher, monkeypatch)
    qapp.processEvents()
    reference = weakref.ref(controller)
    portrait_reference = weakref.ref(controller._portraits) if portraits else None
    controller.shutdown()
    controller.shutdown()
    del controller
    drain(qapp)
    assert reference() is None
    if portraits:
        assert portrait_reference() is None
        facade = render_cache[0]
        facade.render_landed.emit('ttr', 'Flossbud', 'portrait')
        facade.set_promoted.emit('ttr', 'Flossbud')
    # These still-live sources must not address the old controller.
    session.stop()
    keymaps.notify()
    settings.set('float_strip_style', 'flat')
    launcher.changed.emit()
    source.ghost_pointer_event.emit(('press', []))
    drain(qapp)
    replacement = construct(session, keymaps, settings, launcher, monkeypatch)
    try:
        assert replacement.follower.surfaces()
        assert all(s.strip.style_name() == 'flat' for s in replacement.follower.surfaces().values())
    finally:
        replacement.shutdown()


def test_shutdown_does_not_disconnect_another_controller_or_session_listener(qapp, monkeypatch):
    session = FakeToonSession.demo(window_ids=['101','102','103','104'])
    settings, keymaps, launcher = Settings(), Keymaps(), Launcher()
    first = construct(session, keymaps, settings, launcher, monkeypatch)
    second = construct(session, keymaps, settings, launcher, monkeypatch)
    observed = []
    session.running_changed.connect(observed.append)
    first.shutdown()
    session.stop()
    qapp.processEvents()
    assert observed == [False]
    assert all(not s.strip.model().running for s in second.follower.surfaces().values())
    second.shutdown()


def test_supplied_follower_does_not_retain_old_popover_manager(qapp):
    session = FakeToonSession.demo(window_ids=['101','102','103','104'])
    follower = StripFollower(Strategy(), Backend(), geometry_fn=lambda _: (100,50,800,600), scale=1)
    controller = StripController(session, follower, keyset_ids=DEMO_KEYSET_IDS, size='small')
    controller.start()
    follower.tracker.stop()
    follower.tracker.sample_now()
    follower.tracker.sample_now()
    settle()
    reference = weakref.ref(controller.popovers)
    controller.shutdown()
    del controller
    drain(qapp)
    assert reference() is None
    replacement = StripController(session, follower, keyset_ids=DEMO_KEYSET_IDS, size='small')
    replacement.start()
    assert len(replacement.follower.surfaces()) == 4
    replacement.shutdown()


def test_queued_old_presentation_changes_cannot_modify_replacement(qapp):
    session = FakeToonSession.demo(window_ids=['101','102','103','104'])
    follower = StripFollower(Strategy(), Backend(), geometry_fn=lambda _: (100,50,800,600), scale=1)
    first = StripController(session, follower, keyset_ids=DEMO_KEYSET_IDS, size='small')
    first.start()
    follower.tracker.stop()
    def post():
        first._style_changed.emit('flat')
        first._size_changed.emit('small')
    worker = threading.Thread(target=post)
    worker.start()
    worker.join()
    first.shutdown()
    second = StripController(session, follower, keyset_ids=DEMO_KEYSET_IDS,
                             style='neon', size='large')
    second.start()
    follower.tracker.stop()
    follower.tracker.sample_now()
    follower.tracker.sample_now()
    settle()
    assert follower.size() == 'large'
    assert all(s.strip.style_name() == 'neon' and s.strip.scale() == 1.5
               for s in follower.surfaces().values())
    second.shutdown()


@pytest.mark.parametrize('kind', ['strip', 'popover'])
def test_queued_mapping_callback_is_cancelled_when_surface_is_destroyed(qapp, kind):
    from PySide6.QtCore import QPoint
    from utils.strips.strip_surface import StripSurface
    from utils.strips.popovers.surface import PopoverSurface
    from utils.strips.popovers.home import HomePanel
    if kind == 'strip':
        surface = StripSurface(Strategy(), Backend(), 1)
        surface.set_game_window('123')
        surface.place((0, 0, 800, 600))
    else:
        surface = PopoverSurface(Strategy(), Backend(), HomePanel())
        surface.present(QPoint(100, 100), 123)
    surface.paintEvent(None)  # queues the first mapped-window attachment
    surface.hide()
    surface.deleteLater()
    drain(qapp)
