"""Tests for PickerCard, the single-row widget used by both picker dialogs."""

import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_card_constructs_for_every_known_slug(qapp):
    from utils.widgets.picker_card import PickerCard
    from utils.launcher_chip import LAUNCHER_CHIP_COLOR
    for slug in LAUNCHER_CHIP_COLOR:
        card = PickerCard(chip_slug=slug, name="X", path="/x")
        assert card is not None


def test_card_with_path_uses_elided_label(qapp):
    from utils.widgets.picker_card import PickerCard, ElidedLabel
    card = PickerCard(chip_slug="wine", name="Plain Wine",
                      path="/home/u/.wine/drive_c/.../CorporateClash.exe")
    # The path label is an ElidedLabel that stores the full string.
    assert isinstance(card._path_label, ElidedLabel)
    assert card._path_label.full_text().endswith("CorporateClash.exe")


def test_card_with_sub_shows_plain_label(qapp):
    """Compat picker rows use `sub` (e.g. 'OFFICIAL') instead of `path`."""
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="proton", name="Proton 9.0-4", sub="OFFICIAL")
    # When `sub` is given, there is no ElidedLabel; just a plain QLabel.
    assert card._path_label is None


def test_active_card_paints_left_stripe(qapp):
    """The active flag exposes a property that QSS / paintEvent can read."""
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x", active=True)
    assert card.property("active") == "true"


def test_set_selected_flips_property_and_repolishes(qapp):
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x")
    assert card.property("selected") == "false"
    card.set_selected(True)
    assert card.property("selected") == "true"
    card.set_selected(False)
    assert card.property("selected") == "false"


def test_clicked_signal_fires_on_mouse_release(qapp):
    from PySide6.QtCore import QPointF, Qt as QtNs
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x")
    fired = []
    card.clicked.connect(lambda: fired.append(True))
    p = QPointF(10.0, 10.0)
    dev = QPointingDevice.primaryPointingDevice()
    # Simulate a left-click on the card.
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, p, p,
        QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, p, p,
        QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
    )
    QApplication.sendEvent(card, press)
    QApplication.sendEvent(card, release)
    assert fired == [True]


def test_stale_card_suppresses_clicked(qapp):
    from PySide6.QtCore import QPointF, Qt as QtNs
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x", stale=True)
    fired = []
    card.clicked.connect(lambda: fired.append(True))
    p = QPointF(10.0, 10.0)
    dev = QPointingDevice.primaryPointingDevice()
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, p, p,
        QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, p, p,
        QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
    )
    QApplication.sendEvent(card, press)
    QApplication.sendEvent(card, release)
    assert fired == []


def test_stale_card_property_is_true(qapp):
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="steam-proton", name="X", path="/x", stale=True)
    assert card.property("stale") == "true"


def test_doubleclick_signal_fires(qapp):
    from PySide6.QtCore import QPointF, Qt as QtNs
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x")
    dbl = []
    card.doubleClicked.connect(lambda: dbl.append(True))
    p = QPointF(10.0, 10.0)
    dev = QPointingDevice.primaryPointingDevice()
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, p, p,
        QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
    )
    QApplication.sendEvent(card, event)
    assert dbl == [True]


def test_doubleclick_does_not_spuriously_emit_clicked(qapp):
    """Full Qt double-click sequence: Press, Release, Press, DblClick, Release.
    Must emit `clicked` exactly once (the first Release) and `doubleClicked`
    exactly once."""
    from PySide6.QtCore import QPointF, Qt as QtNs
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from utils.widgets.picker_card import PickerCard
    card = PickerCard(chip_slug="wine", name="X", path="/x")
    clicked: list[int] = []
    dbl: list[int] = []
    card.clicked.connect(lambda: clicked.append(1))
    card.doubleClicked.connect(lambda: dbl.append(1))
    p = QPointF(10.0, 10.0)
    dev = QPointingDevice.primaryPointingDevice()
    for typ in (
        QMouseEvent.Type.MouseButtonPress,
        QMouseEvent.Type.MouseButtonRelease,
        QMouseEvent.Type.MouseButtonPress,
        QMouseEvent.Type.MouseButtonDblClick,
        QMouseEvent.Type.MouseButtonRelease,
    ):
        QApplication.sendEvent(card, QMouseEvent(
            typ, p, p, QtNs.LeftButton, QtNs.LeftButton, QtNs.NoModifier, dev,
        ))
    assert clicked == [1]
    assert dbl == [1]
