from PySide6.QtCore import QSize
from utils.widgets.primary_toon_slot import PrimaryToonSlot


def test_fixed_38px(qapp):
    w = PrimaryToonSlot(game="ttr")
    assert w.sizeHint() == QSize(38, 38)
    assert w.minimumSize() == QSize(38, 38)


def test_set_toon_marks_set(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species="DOG", accent="#8ab6f0", slot_number=1)
    assert w.is_set() is True


def test_unset_is_default(qapp):
    w = PrimaryToonSlot(game="cc")
    assert w.is_set() is False


def test_clear_resets(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species="DOG", accent="#8ab6f0", slot_number=1)
    w.clear()
    assert w.is_set() is False


def test_click_emits(qapp):
    w = PrimaryToonSlot(game="ttr")
    fired = []
    w.clicked.connect(lambda: fired.append(1))
    w._emit_click()
    assert fired == [1]


def test_paints_without_error_both_states(qapp):
    # grab() exercises paintEvent for set + unset; must not raise
    w = PrimaryToonSlot(game="ttr"); w.resize(38, 38)
    w.grab()
    w.set_toon(species="HORSE", accent=None, slot_number=2)  # accent None -> game accent
    w.grab()


def test_set_toon_none_species_is_unset_but_keeps_badge(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species=None, accent=None, slot_number=3)
    assert w.is_set() is False
    w.grab()  # paints dashed + badge without error
