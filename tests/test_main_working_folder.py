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


def test_a_build_with_no_standard_streams_gets_streams_to_nowhere(tmp_path):
    """A windowed build started with no console and no redirected handles has
    sys.stdout and sys.stderr set to None; --self-check then wrote to None,
    raised, and sat behind an error box. The first lines of main.py give the
    process real streams before anything writes."""
    import subprocess
    import sys
    source = open(main.__file__, encoding="utf-8").read()
    head = source[:source.index("# Windows: when this is the copy relaunched")]
    assert "os.devnull" in head
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\nsys.stdout = None\nsys.stderr = None\n"
        + head.replace("from __future__ import annotations", "")
        + "\nsys.stdout.write('x')\nsys.stdout.flush()\nsys.stderr.flush()\n"
        + f"open(r'{tmp_path / 'ok.txt'}', 'w').write(type(sys.stdout).__name__)\n",
        encoding="utf-8")
    result = subprocess.run([sys.executable, str(probe)], capture_output=True, timeout=60)
    assert result.returncode == 0
    assert (tmp_path / "ok.txt").read_text() == "TextIOWrapper"
