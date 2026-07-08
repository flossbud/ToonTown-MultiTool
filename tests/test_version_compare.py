import pytest
from utils.version_compare import parse, is_beta_tag, is_newer, compare, ParsedVersion


def test_parse_stable_tag():
    assert parse("v2.3.0") == ParsedVersion(2, 3, 0, "")


def test_parse_beta_tag():
    assert parse("v2.3.0-a") == ParsedVersion(2, 3, 0, "a")


def test_parse_rc_tag():
    assert parse("v2.2.0-rc1") == ParsedVersion(2, 2, 0, "rc1")


def test_parse_malformed_returns_none():
    assert parse("not-a-tag") is None
    assert parse("") is None
    assert parse("v2.3") is None


def test_is_beta_tag():
    assert is_beta_tag("v2.3.0-a") is True
    assert is_beta_tag("v2.2.0-rc1") is True
    assert is_beta_tag("v2.3.0") is False
    assert is_beta_tag("not-a-tag") is False


@pytest.mark.parametrize("local_v,local_b,remote_v,remote_b,expected", [
    # patch bump
    ("v2.3.0", 100, "v2.3.1", 101, True),
    ("v2.3.1", 101, "v2.3.0", 100, False),
    # minor bump
    ("v2.3.0", 100, "v2.4.0", 110, True),
    # major bump
    ("v2.3.0", 100, "v3.0.0", 200, True),
    # suffix bump within beta
    ("v2.3.0-a", 100, "v2.3.0-b", 105, True),
    ("v2.3.0-b", 105, "v2.3.0-a", 100, False),
    # build-only bump (same version, higher build)
    ("v2.3.0-a", 100, "v2.3.0-a", 101, True),
    # same version + build
    ("v2.3.0-a", 100, "v2.3.0-a", 100, False),
    # build lower (treat as not newer)
    ("v2.3.0-a", 101, "v2.3.0-a", 100, False),
    # stable release supersedes corresponding beta
    ("v2.3.0-b", 999, "v2.3.0", 0, True),
])
def test_is_newer(local_v, local_b, remote_v, remote_b, expected):
    lv = parse(local_v)
    rv = parse(remote_v)
    assert is_newer(lv, local_b, rv, remote_b) is expected


@pytest.mark.parametrize("older,newer", [
    # Dotted numeric suffixes must order numerically, not lexicographically.
    # "alpha.10" < "alpha.9" as strings, which silently stalled the updater.
    ("v0.7.0-alpha.9", "v0.7.0-alpha.10"),
    ("v0.7.0-alpha.2", "v0.7.0-alpha.10"),
    ("v0.7.0-alpha.9", "v0.7.0-alpha.100"),
    # Single-digit ordering keeps working.
    ("v0.7.0-alpha.1", "v0.7.0-alpha.2"),
    ("v0.7.0-alpha.4", "v0.7.0-alpha.5"),
    # Label ordering: alpha < beta < rc, regardless of the numeric part.
    ("v0.8.0-alpha.10", "v0.8.0-beta.1"),
    ("v0.8.0-beta.2", "v0.8.0-rc.1"),
    ("v0.8.0-alpha.99", "v0.8.0-rc.1"),
    # A bare label ranks below the same label with a number (alpha < alpha.1).
    ("v0.8.0-alpha", "v0.8.0-alpha.1"),
    # A numeric segment ranks below an alphanumeric one at the same position.
    ("v0.8.0-alpha.1", "v0.8.0-alpha.beta"),
    # Stable still supersedes every pre-release, including double-digit ones.
    ("v0.8.0-alpha.10", "v0.8.0"),
    ("v0.8.0-rc.9", "v0.8.0"),
    # Version tuple still outranks any suffix comparison.
    ("v0.7.0-rc.9", "v0.8.0-alpha.1"),
    # Legacy single-letter suffixes from the pre-restructure tags.
    ("v2.3.0-a", "v2.3.0-b"),
    ("v2.3.0-b", "v2.3.0-rc1"),
])
def test_suffix_ordering(older, newer):
    assert compare(parse(older), parse(newer)) == -1
    assert compare(parse(newer), parse(older)) == 1
    assert is_newer(parse(older), 0, parse(newer), 0) is True
    assert is_newer(parse(newer), 0, parse(older), 0) is False


def test_numerically_equal_suffixes_fall_through_to_build_number():
    """`alpha.01` and `alpha.1` are the same release; the build number breaks the tie."""
    assert compare(parse("v0.8.0-alpha.01"), parse("v0.8.0-alpha.1")) == 0
    assert is_newer(parse("v0.8.0-alpha.01"), 100, parse("v0.8.0-alpha.1"), 101) is True
    assert is_newer(parse("v0.8.0-alpha.01"), 101, parse("v0.8.0-alpha.1"), 100) is False


def test_compare_remote_newer_returns_negative():
    assert compare(parse("v2.3.0"), parse("v2.3.1")) == -1


def test_compare_local_newer_returns_positive():
    assert compare(parse("v2.3.1"), parse("v2.3.0")) == 1


def test_compare_equal_versions_returns_zero():
    assert compare(parse("v2.3.0-a"), parse("v2.3.0-a")) == 0


def test_is_newer_returns_false_on_none_inputs():
    v = parse("v2.3.0")
    assert is_newer(None, 0, v, 100) is False
    assert is_newer(v, 100, None, 0) is False
    assert is_newer(None, 0, None, 0) is False
