"""User visibility is independent of game movement and native attachment."""
from dataclasses import replace
import pytest
from PySide6.QtWidgets import QWidget
from utils import chord_capture_state
from utils.strips import layout as L
from tests.test_strips_controller import Keymaps, rig, settle


def test_toggle_signal_is_idempotent_and_stopped_session_still_shows(rig):
    session, controller, _ = rig()
    changed = []
    controller.user_hidden_changed.connect(changed.append)
    assert controller.user_hidden() is False
    controller.set_user_hidden(True)
    controller.set_user_hidden(True)
    assert controller.user_hidden() is True
    assert all(not s.is_presented() for s in controller.follower.surfaces().values())
    session.stop()
    controller.toggle_user_hidden()
    settle()
    assert changed == [True, False]
    assert all(s.is_presented() for s in controller.follower.surfaces().values())
    assert all(s.strip.model().dimmed for s in controller.follower.surfaces().values())


def test_hide_closes_popovers_counters_and_capture_before_releasing_visibility(rig):
    _, controller, _ = rig(keymaps=Keymaps())
    card = controller.open_editor('102', 1)
    settle()
    card.begin_capture(card.model().actions[0][0])
    assert chord_capture_state.is_active()
    shown_surfaces = list(controller.follower.surfaces().values())
    counters = controller.popovers.counters_surface('101')
    assert counters.is_presented()
    controller.set_user_hidden(True)
    assert not chord_capture_state.is_active()
    assert QWidget.keyboardGrabber() is None
    assert controller.popovers.open_tag('102') == ''
    assert not controller.popovers.watch.is_watching()
    assert not counters.is_presented()
    assert all(not s.is_presented() and s.windowOpacity() == 0 for s in shown_surfaces)
    assert all(s.backend.last.isEmpty() for s in shown_surfaces)


def test_new_toons_and_changed_models_are_hidden_until_user_shows_them(rig):
    session, controller, rects = rig()
    controller.set_user_hidden(True)
    template = session.toon('104')
    session.remove_toon('104')
    rects['105'] = (100, 50, 800, 600)
    session.add_toon(replace(template, window_id='105', name='Fresh toon'))
    controller.follower.tracker.sample_now()
    controller.follower.tracker.sample_now()
    session.set_enabled('101', False)
    settle()
    fresh = controller.follower.surface('105')
    assert not fresh.is_presented()
    assert not controller.follower.surface('101').strip.model().enabled
    controller.set_user_hidden(False)
    settle()
    assert fresh.is_presented()
    assert fresh.strip.model().name == 'Fresh toon'
    assert not controller.follower.surface('101').strip.model().enabled


@pytest.mark.parametrize('reason', ['moving', 'attachment', 'unmapped'])
def test_show_does_not_override_another_reason_for_concealment(rig, reason):
    _, controller, _ = rig()
    surface = controller.follower.surface('101')
    controller.set_user_hidden(True)
    if reason == 'moving':
        surface.conceal()
    elif reason == 'attachment':
        surface._attached = False
    else:
        surface.hide()
    controller.set_user_hidden(False)
    assert not surface.is_presented()


def test_hidden_home_and_identity_cannot_open_popovers(rig):
    _, controller, _ = rig()
    controller.set_user_hidden(True)
    controller.toggle_home_panel('101')
    controller._on_context('101', L.PORTRAIT, 0)
    controller.popovers.set_identity_hover('101', True)
    assert controller.popovers.open_tag('101') == ''
    assert not controller.popovers.counters_shown('101')
