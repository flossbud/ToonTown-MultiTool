"""Source-run adjudication + policy-on-every-read in _perform_check.

All git/network behavior is monkeypatched; FakeResponse mirrors
tests/test_update_checker.py.
"""
import json

import pytest

from utils import update_checker
from utils.source_release_state import ReleaseState
from utils.settings_keys import (
    UPDATE_LAST_CHECK_AT,
    UPDATE_LAST_CHECK_RESULT,
    UPDATE_SKIPPED_VERSION,
)

SHA = "c" * 40


class FakeSettings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


def _release(tag, body="Build: 500"):
    return {"tag_name": tag, "body": body, "draft": False,
            "html_url": "u", "assets": []}


@pytest.fixture
def env(monkeypatch):
    """Source run at 0.7.0-alpha.2 with v0.7.0-alpha.3 published."""
    monkeypatch.setattr("utils.version.APP_VERSION", "0.7.0-alpha.2")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 400)
    monkeypatch.setattr("utils.build_info.is_source_run", lambda: True)
    monkeypatch.setattr(update_checker, "_resolve_release_commit",
                        lambda tag, api_get: SHA)
    monkeypatch.setattr(update_checker, "_head_sha", lambda: "h" * 40)
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **k: FakeResponse(200, [_release("v0.7.0-alpha.3")]))
    return FakeSettings()


def _check(sm, *, manual=False):
    return update_checker._perform_check(sm, manual=manual)


@pytest.mark.parametrize("state,expect", [
    (ReleaseState.AT_OR_PAST, "none"),
    (ReleaseState.DIVERGENT, "none"),
    (ReleaseState.BEHIND, "update"),
    (ReleaseState.UNPROVABLE, "update"),
])
def test_auto_source_states(env, monkeypatch, state, expect):
    monkeypatch.setattr(update_checker, "_classify", lambda sha: state)
    assert _check(env)["kind"] == expect


def test_manual_skips_adjudication(env, monkeypatch):
    def boom(sha):
        raise AssertionError("manual must not classify")

    monkeypatch.setattr(update_checker, "_classify", boom)
    assert _check(env, manual=True)["kind"] == "update"


def test_packaged_build_skips_adjudication(env, monkeypatch):
    monkeypatch.setattr("utils.build_info.is_source_run", lambda: False)

    def boom(sha):
        raise AssertionError("packaged must not classify")

    monkeypatch.setattr(update_checker, "_classify", boom)
    assert _check(env)["kind"] == "update"


def test_unresolvable_sha_is_unprovable_banner(env, monkeypatch):
    monkeypatch.setattr(update_checker, "_resolve_release_commit",
                        lambda tag, api_get: None)

    def boom(sha):
        raise AssertionError("must not classify without a sha")

    monkeypatch.setattr(update_checker, "_classify", boom)
    assert _check(env)["kind"] == "update"


def test_cached_update_is_reclassified_on_auto(env, monkeypatch):
    """The manual-then-auto replay hole: a manual check caches the release;
    the next AUTO check must re-apply the source policy to the cached
    release instead of replaying the banner."""
    monkeypatch.setattr(update_checker, "_classify",
                        lambda sha: ReleaseState.DIVERGENT)
    assert _check(env, manual=True)["kind"] == "update"  # caches release
    assert env.get(UPDATE_LAST_CHECK_RESULT)

    def no_network(*a, **k):
        raise AssertionError("auto within TTL must hit the cache")

    monkeypatch.setattr("requests.get", no_network)
    assert _check(env)["kind"] == "none"  # reclassified, suppressed


def test_cache_hit_does_not_resolve_again(env, monkeypatch):
    calls = []
    monkeypatch.setattr(update_checker, "_resolve_release_commit",
                        lambda tag, api_get: calls.append(1) or SHA)
    monkeypatch.setattr(update_checker, "_classify",
                        lambda sha: ReleaseState.DIVERGENT)
    _check(env)                      # network path: resolves once
    assert len(calls) == 1
    _check(env)                      # cache hit: classification only
    assert len(calls) == 1


def test_head_sha_change_invalidates_cache(env, monkeypatch):
    monkeypatch.setattr(update_checker, "_classify",
                        lambda sha: ReleaseState.DIVERGENT)
    assert _check(env)["kind"] == "none"
    # A commit/branch switch changes HEAD: the cached decision must not
    # be replayed against the old stamp.
    monkeypatch.setattr(update_checker, "_head_sha", lambda: "i" * 40)
    fetched = []
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **k: fetched.append(1) or FakeResponse(
            200, [_release("v0.7.0-alpha.3")]))
    assert _check(env)["kind"] == "none"
    assert fetched  # stamp mismatch forced a refetch


def test_skip_list_still_honored_on_auto(env, monkeypatch):
    monkeypatch.setattr(update_checker, "_classify",
                        lambda sha: ReleaseState.BEHIND)
    env.set(UPDATE_SKIPPED_VERSION, "v0.7.0-alpha.3")
    assert _check(env)["kind"] == "none"


def test_no_update_when_local_is_newer(env, monkeypatch):
    monkeypatch.setattr("utils.version.APP_VERSION", "0.8.0")
    assert _check(env)["kind"] == "none"
