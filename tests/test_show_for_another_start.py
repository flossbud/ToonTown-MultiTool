"""What the running copy does when another start asks for its window
(main._show_for_another_start, wired to the single-copy guard).

The launchpad window comes back as it was left, from hidden or minimized;
the classic window is raised when it is up and left alone in Float UI.
Built offscreen: construction checks.
"""

import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMainWindow

from tests.test_launchpad_window import isolated, window  # noqa: F401 (fixtures)


def test_the_hidden_launchpad_window_comes_back(window, qapp):
    import main
    from utils.widgets.launchpad import lifecycle
    window.hide()                         # what the lifecycle's HIDE does
    qapp.processEvents()
    assert window.lifecycle.window == lifecycle.HIDDEN
    main._show_for_another_start(window)
    qapp.processEvents()
    assert window.isVisible() and not window.isMinimized()
    assert window.lifecycle.window == lifecycle.VISIBLE


def test_the_launchpad_window_comes_back_on_the_sheet_it_was_left_on(window, qapp):
    import main
    from utils.widgets.launchpad.header import SHEET_SETTINGS
    window.open_sheet(SHEET_SETTINGS)
    window.hide()
    qapp.processEvents()
    main._show_for_another_start(window)
    qapp.processEvents()
    assert window.isVisible()
    assert window.open_sheet_name() == SHEET_SETTINGS


def test_the_classic_window_is_raised_when_it_is_up(qapp):
    import main
    win = QMainWindow()
    try:
        win.showMinimized()
        qapp.processEvents()
        main._show_for_another_start(win)
        qapp.processEvents()
        assert win.isVisible() and not win.isMinimized()
    finally:
        win.close()


def test_the_classic_window_in_float_ui_is_left_alone(qapp):
    import main
    win = QMainWindow()                   # hidden: Float UI owns the screen
    try:
        main._show_for_another_start(win)
        qapp.processEvents()
        assert not win.isVisible()
    finally:
        win.close()
