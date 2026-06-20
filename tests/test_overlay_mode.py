from utils.overlay.mode import WindowMode


def test_modes_exist_and_are_distinct():
    assert WindowMode.FRAMED != WindowMode.TRANSPARENT
    assert {WindowMode.FRAMED, WindowMode.TRANSPARENT} == set(WindowMode)
