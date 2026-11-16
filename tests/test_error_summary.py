"""summarize_error: pill-sized error summaries for launcher cards."""
from utils.error_summary import summarize_error


def test_summarize_error_empty_returns_failed():
    assert summarize_error("") == "Failed"


def test_summarize_error_401_routes_to_bad_credentials():
    assert summarize_error("HTTP 401 Unauthorized") == "Bad credentials"
    assert summarize_error("bad creds in the response") == "Bad credentials"
    assert summarize_error("Incorrect username or password") == "Bad credentials"


def test_summarize_error_network_routes():
    assert summarize_error("Network unreachable") == "Network error"
    assert summarize_error("Connection refused") == "Network error"
    assert summarize_error("Request timeout") == "Network error"


def test_summarize_error_queue_timeout_takes_precedence():
    # "queue" + "timeout" must route to "Queue timed out", not "Network error".
    assert summarize_error("Queue timed out after 10 minutes") == "Queue timed out"


def test_summarize_error_engine_not_found_routes():
    assert summarize_error("Engine not found at ~/foo") == "Engine not found"
    assert summarize_error("TTREngine missing") == "Engine not found"


def test_summarize_error_runtime_routes():
    assert summarize_error("Wine prefix locked") == "Runtime error"
    assert summarize_error("Proton dispatch failed") == "Runtime error"
    assert summarize_error("umu-run exited 1") == "Runtime error"


def test_summarize_error_not_installed_routes_to_runtime_missing():
    """Bottles flatpak / Steam / Lutris 'X not installed' stderr should
    map to 'Runtime missing' on the band. Reported in the wild as
    'error: app/com.usebottles.bottles/x86_64/master not installed' when
    the user has only the host-native Bottles but TTMT tries flatpak."""
    assert summarize_error(
        "error: app/com.usebottles.bottles/x86_64/master not installed"
    ) == "Runtime missing"
    assert summarize_error("Proton runtime is not installed") == "Runtime missing"


def test_summarize_error_exact_32_chars_no_truncation():
    msg = "x" * 32
    assert summarize_error(msg) == msg


def test_summarize_error_33_chars_truncates_with_ellipsis():
    msg = "x" * 33
    result = summarize_error(msg)
    # 32 chars + the ellipsis character.
    assert result == ("x" * 32 + "…")
    assert len(result) == 33  # 32 x's + 1 ellipsis char


def test_summarize_error_unmatched_short_message_returned_as_is():
    assert summarize_error("Some plain error") == "Some plain error"
