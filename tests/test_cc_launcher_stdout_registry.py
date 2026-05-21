from pathlib import Path

from services import cc_launcher


def test_get_stdout_path_for_unknown_pid_returns_none():
    assert cc_launcher.get_stdout_path_for_pid(9999999) is None


def test_register_and_lookup(tmp_path):
    log_path = tmp_path / "fake-stdout.log"
    log_path.write_text("")
    pid = 12345
    try:
        cc_launcher._register_stdout_path(pid, log_path)
        assert cc_launcher.get_stdout_path_for_pid(pid) == log_path
    finally:
        cc_launcher._unregister_stdout_path(pid)


def test_unregister_clears_mapping(tmp_path):
    log_path = tmp_path / "fake-stdout.log"
    log_path.write_text("")
    pid = 12346
    cc_launcher._register_stdout_path(pid, log_path)
    cc_launcher._unregister_stdout_path(pid)
    assert cc_launcher.get_stdout_path_for_pid(pid) is None


def test_double_unregister_is_safe(tmp_path):
    cc_launcher._unregister_stdout_path(99998)  # never registered
    cc_launcher._unregister_stdout_path(99998)  # again, still safe
