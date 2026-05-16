import pytest
from utils.version_compare import parse, is_beta_tag, is_newer, ParsedVersion


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
])
def test_is_newer(local_v, local_b, remote_v, remote_b, expected):
    lv = parse(local_v)
    rv = parse(remote_v)
    assert is_newer(lv, local_b, rv, remote_b) is expected
