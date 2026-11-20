"""An installed Windows build leaves its install folder at startup, so no
process it starts can hold that folder as its working folder and block an
update from moving the installed version aside."""
import os

import main


def test_an_installed_windows_build_moves_to_the_home_folder():
    went = []
    assert main._leave_install_folder("win32", True, went.append) is True
    assert went == [os.path.expanduser("~")]


def test_source_runs_and_other_platforms_stay_where_they_are():
    went = []
    assert main._leave_install_folder("win32", False, went.append) is False
    assert main._leave_install_folder("linux", True, went.append) is False
    assert main._leave_install_folder("darwin", True, went.append) is False
    assert went == []


def test_a_home_folder_that_cannot_be_entered_is_not_fatal():
    def refuse(_path):
        raise OSError("denied")
    assert main._leave_install_folder("win32", True, refuse) is False


def test_it_runs_before_anything_else_starts():
    source = open(main.__file__, encoding="utf-8").read()
    entry = source.index('if __name__ == "__main__":')
    assert source.index("    _leave_install_folder()", entry) < source.index(
        "_instance_guard.run_startup(", entry)
