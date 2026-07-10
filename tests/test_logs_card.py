import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.logs_console.model import BUFFER_CAP, LINE_ROLE


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def card(qapp):
    from utils.widgets.logs_console.logs_card import LogsCard
    c = LogsCard()
    c.resize(868, 640)
    c.show()
    QApplication.processEvents()
    return c


def test_card_uses_purple_card_surface(card):
    assert card.surface.accent_key == "purple"
    assert card.surface.title_label.text() == "Logs"


def test_append_reaches_the_model_and_status(card):
    card.append("[Credentials] Keyring ready")
    card.append("[TTR API] Login OK")
    QApplication.processEvents()
    assert card.model.rowCount() == 2
    assert "2 lines" in card.status.text()
    assert "following" in card.status.text()


def test_status_reflects_paused(card):
    for i in range(60):
        card.append(f"line {i}")
    QApplication.processEvents()
    card.pane.set_following(False)
    assert "paused" in card.status.text()


def test_apply_theme_cascades_both_ways(card):
    card.apply_theme(False)
    card.apply_theme(True)   # no crash; component token flips are pinned in their own suites


def test_dot_animates_only_while_visible(card):
    # The card fixture is shown; the dot's showEvent started the pulse.
    assert card.dot._anim is not None
    card.hide()
    QApplication.processEvents()
    assert card.dot._anim is None
    card.show()
    QApplication.processEvents()
    assert card.dot._anim is not None


def test_scope_segment_filters_and_clears_stale_state(card):
    card.append("[Service] input line")
    card.append("[TTR API] api line")
    QApplication.processEvents()
    card.segment.index_changed.emit(2)           # Input — drives the real connect
    assert card.proxy.scope() == "input"
    assert card.proxy.rowCount() == 1


def test_search_filters_as_you_type(card):
    card.append("[Credentials] Keyring ready")
    card.append("[Credentials] storage available")
    card.search.setText("keyring")
    QApplication.processEvents()
    assert card.proxy.rowCount() == 1
    assert "matching" in card.status.text()
    card.search.setText("")
    QApplication.processEvents()
    assert "matching" not in card.status.text()


def test_follow_button_toggles_pane(card):
    card.follow_btn.click()
    assert not card.pane.is_following()
    card.follow_btn.click()
    assert card.pane.is_following()


def test_empty_state_message_includes_query(card):
    card.append("something")
    card.search.setText("zzz-nope")
    QApplication.processEvents()
    assert card.pane.empty_label.isVisible()
    assert 'zzz-nope' in card.pane.empty_label.text()
    card.search.setText("")
    QApplication.processEvents()


def test_pane_scrollbar_is_the_kit_autohide(card):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    assert isinstance(card.pane.view.verticalScrollBar(), AutoHideScrollBar)


def test_chips_are_first_seen_tags_of_scope(card):
    card.append("[Credentials] a")
    card.append("[Service] b")
    card.append("[Credentials] c")
    card.append("untagged")
    QApplication.processEvents()
    labels = [c.text() for c in card.chips()]
    assert labels.count("[Credentials]") == 1          # dedup, first-seen order
    assert labels.index("[Credentials]") < labels.index("[Service]")
    card._on_scope_changed(1)                          # Terminal scope
    assert "[Service]" not in [c.text() for c in card.chips()]
    card._on_scope_changed(0)


def test_chip_toggle_filters_and_status_matches(card):
    card.append("[Credentials] x")
    card.append("[Service] y")
    QApplication.processEvents()
    chip = next(c for c in card.chips() if c.text() == "[Credentials]")
    chip.click()
    QApplication.processEvents()
    visible_tags = {card.proxy.index(i, 0).data(LINE_ROLE).tag
                    for i in range(card.proxy.rowCount())}
    assert visible_tags == {"[Credentials]"}
    assert "matching" in card.status.text()
    chip.click()
    QApplication.processEvents()
    assert card.proxy.rowCount() >= 2


def test_active_chip_leaving_scope_is_dropped_from_filter(card):
    card.append("[Credentials] x")
    card.append("[Service] y")
    QApplication.processEvents()
    chip = next(c for c in card.chips() if c.text() == "[Service]")
    chip.click()
    card._on_scope_changed(1)                          # Terminal: no [Service] tag
    assert card.proxy.rowCount() > 0                   # filter dropped, not empty
    card._on_scope_changed(0)


def test_chips_survive_ring_buffer_saturation(card):
    # Regression pin: buffer eviction rotates the ring's first-seen tag order.
    # The chip row must NOT rebuild while the tag SET is unchanged — the same
    # widget objects, in the same order, before and after saturation.
    mid_chips = None
    mid_ids = None
    for i in range(BUFFER_CAP + 20):
        card.append(f"[Service] s {i}" if i % 2 else f"[Credentials] c {i}")
        if i == 10:
            QApplication.processEvents()
            mid_chips = card.chips()                   # hold refs: no id reuse
            mid_ids = [id(c) for c in mid_chips]
    QApplication.processEvents()
    assert mid_ids is not None and len(mid_ids) == 2
    assert [id(c) for c in card.chips()] == mid_ids


def test_apply_theme_restyles_existing_chips(card):
    card.append("[Credentials] themed line")
    QApplication.processEvents()
    card.apply_theme(False)
    card.apply_theme(True)
    assert [c.text() for c in card.chips()] == ["[Credentials]"]


def test_checked_state_survives_new_tag_rebuild(card):
    card.append("[Service] a")
    card.append("[Credentials] b")
    QApplication.processEvents()
    chip = next(c for c in card.chips() if c.text() == "[Service]")
    chip.click()
    QApplication.processEvents()
    card.append("[Hotkey] brand new tag")              # forces a chip rebuild
    QApplication.processEvents()
    service = next(c for c in card.chips() if c.text() == "[Service]")
    assert service.isChecked()
    visible_tags = {card.proxy.index(i, 0).data(LINE_ROLE).tag
                    for i in range(card.proxy.rowCount())}
    assert visible_tags == {"[Service]"}
