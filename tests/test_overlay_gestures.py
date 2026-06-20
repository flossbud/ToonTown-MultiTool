from PySide6.QtCore import QPoint
from utils.overlay.gestures import is_drag, DRAG_THRESHOLD


def test_small_move_is_click():
    assert is_drag(QPoint(0, 0), QPoint(3, 0)) is False


def test_large_move_is_drag():
    assert is_drag(QPoint(0, 0), QPoint(DRAG_THRESHOLD + 1, 0)) is True
