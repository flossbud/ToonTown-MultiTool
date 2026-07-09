from datetime import datetime

from utils.widgets.logs_console.records import (
    LogLine, classify_level, classify_source, format_line, make_line,
    split_leading_tag,
)


# ── source routing: verbatim parity with the old DebugTab.append_log ──
def test_input_tags_route_input():
    for tag in ("[Input]", "[KeepAlive]", "[Hotkey]", "[Service]"):
        assert classify_source(f"{tag} something") == "input"


def test_api_tags_route_api():
    for tag in ("[TTR API]", "[Profile]", "[Launch]"):
        assert classify_source(f"{tag} something") == "api"


def test_everything_else_routes_raw():
    assert classify_source("[Credentials] Keyring ready") == "raw"
    assert classify_source("plain untagged line") == "raw"


def test_routing_is_containment_not_prefix():
    # Parity with the old code: tag anywhere in the message routes.
    assert classify_source("note: [Service] restarted") == "input"


# ── tag split ──
def test_leading_tag_is_split_and_stripped():
    assert split_leading_tag("[Credentials] Keyring ready") == ("[Credentials]", "Keyring ready")


def test_unknown_leading_tag_is_still_a_tag():
    assert split_leading_tag("[EasterEgg] Sent shift+f1") == ("[EasterEgg]", "Sent shift+f1")


def test_untagged_and_midline_tag_stay_whole():
    assert split_leading_tag("plain line") == ("", "plain line")
    assert split_leading_tag("note: [Service] restarted") == ("", "note: [Service] restarted")


# ── level classifier ──
def test_error_keywords():
    assert classify_level("Login attempt 1 failed: timeout") == "error"
    assert classify_level("[Launch] Could not start the official CC launcher.") == "error"
    assert classify_level("[KeepAlive] Error: boom") == "error"


def test_warn_keywords():
    assert classify_level("KWallet unavailable, falling back to SecretService") == "warn"
    assert classify_level("Log tail slow, retrying in 2 s") == "warn"


def test_ok_keywords_word_boundary():
    assert classify_level("Login OK") == "ok"
    assert classify_level("Keyring backend detected: SecretService") == "ok"
    assert classify_level("cookie token issued") == "ok"     # "issued" hits, not "token"
    assert classify_level("broken tokens everywhere") == "info"  # no bare-substring "ok"


def test_precedence_error_beats_warn_beats_ok():
    assert classify_level("retrying after login failed") == "error"
    assert classify_level("retry succeeded") == "warn"


def test_default_info():
    assert classify_level("Platform: Linux (Flatpak)") == "info"


# ── make_line / format_line ──
def test_make_line_explicit_level_wins():
    line = make_line("[TTR API] Login failed", level="info")
    assert line.level == "info"


def test_make_line_classifies_when_no_level():
    line = make_line("[TTR API] Login failed")
    assert line.level == "error"
    assert line.source == "api"
    assert line.tag == "[TTR API]"
    assert line.message == "Login failed"


def test_format_line_recomposes_tag_and_pads_timestamp():
    t = datetime(2026, 7, 9, 17, 57, 13)
    line = LogLine(time=t, source="raw", tag="[Credentials]",
                   level="info", message="Keyring ready")
    assert format_line(line) == "[17:57:13] [Credentials] Keyring ready"
    bare = LogLine(time=t, source="raw", tag="", level="info", message="hi")
    assert format_line(bare) == "[17:57:13] hi"


# ── degenerate inputs ──
def test_empty_and_whitespace_classify_info_and_dont_raise():
    assert classify_level("") == "info"
    assert classify_level("   ") == "info"
    make_line("")  # must not raise


def test_format_line_empty_message_keeps_trailing_space():
    t = datetime(2026, 7, 9, 17, 57, 13)
    empty = LogLine(time=t, source="raw", tag="", level="info", message="")
    assert format_line(empty) == "[17:57:13] "


def test_make_line_honors_injected_clock():
    t = datetime(2026, 7, 9, 1, 2, 3)
    assert make_line("x", now=t).time == t


def test_multiword_phrases_are_word_boundaried():
    # "could nother" must not substring-match the "could not" phrase.
    assert classify_level("the code could nother") == "info"
