import json
import time
from unittest.mock import MagicMock

import pytest

from utils import update_checker
from utils.update_checker import (
    UpdateChecker,
    select_release,
    parse_build_from_body,
    CACHE_TTL_SECONDS,
)


def _release(tag, body="", prerelease=False, draft=False, assets=None):
    return {
        "tag_name": tag,
        "name": tag,
        "body": body,
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets or [],
        "html_url": f"https://github.com/flossbud/ToonTownMultiTool-v2/releases/tag/{tag}",
    }


def test_parse_build_from_body_extracts_int():
    assert parse_build_from_body("Build: 458\n\nNotes here.") == 458


def test_parse_build_from_body_returns_none_when_missing():
    assert parse_build_from_body("Just some release notes.") is None


def test_select_release_picks_alpha_with_prerelease_false():
    """Post-rebrand: alpha-tagged release with prerelease=false (the new
    'latest' shape per the release-flow-restructure spec) must be
    selectable by select_release. Prior behavior skipped it via the
    tag_is_beta != bool(prerelease) cross-check."""
    releases = [
        _release("v0.6.0-alpha.3", body="Build: 1234", prerelease=False),
        _release("v0.6.0-alpha.2", body="Build: 1200", prerelease=True),
    ]
    chosen = select_release(releases)
    assert chosen is not None
    assert chosen["tag_name"] == "v0.6.0-alpha.3"


def test_select_release_picks_newest_by_tuple_compare():
    """Without channel filtering: highest (major, minor, patch) wins, then
    suffix ordering (stable beats pre-release), then build number."""
    releases = [
        _release("v0.5.0-alpha.2", body="Build: 100", prerelease=True),
        _release("v0.6.0-alpha.3", body="Build: 200", prerelease=False),
        _release("v0.6.0-alpha.4", body="Build: 300", prerelease=True),
    ]
    chosen = select_release(releases)
    assert chosen["tag_name"] == "v0.6.0-alpha.4"


def test_select_release_picks_highest_by_tuple_regardless_of_prerelease():
    """Replacement for the prior 'in_channel_beta' test: post-rebrand,
    channel filtering is dropped. A stable v2.3.0 wins over v2.3.0-b
    by suffix ordering, regardless of any beta-vs-stable concept."""
    releases = [
        _release("v2.3.0-a", body="Build: 458", prerelease=True),
        _release("v2.3.0-b", body="Build: 470", prerelease=True),
        _release("v2.3.0", body="Build: 500", prerelease=False),
    ]
    chosen = select_release(releases)
    assert chosen["tag_name"] == "v2.3.0"


def test_select_release_alpha_tag_visible_to_any_install():
    """Replacement for the prior 'in_channel_stable' test: every install
    sees the same feed. A v2.4.0-a release is higher by tuple compare
    than v2.3.0, so it wins."""
    releases = [
        _release("v2.2.0", body="Build: 400", prerelease=False),
        _release("v2.3.0", body="Build: 500", prerelease=False),
        _release("v2.4.0-a", body="Build: 600", prerelease=True),
    ]
    chosen = select_release(releases)
    assert chosen["tag_name"] == "v2.4.0-a"


def test_select_release_drops_drafts():
    releases = [
        _release("v2.3.0", body="Build: 500", prerelease=False, draft=True),
    ]
    assert select_release(releases) is None


def test_select_release_skips_malformed_tags():
    releases = [
        _release("not-a-tag", body="Build: 999", prerelease=False),
        _release("v2.3.0", body="Build: 500", prerelease=False),
    ]
    chosen = select_release(releases)
    assert chosen["tag_name"] == "v2.3.0"


def test_select_release_returns_none_for_empty():
    assert select_release([]) is None


# Integration via UpdateChecker
class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError
            raise HTTPError(f"{self.status_code}")


def test_check_emits_update_available(monkeypatch):
    sm = MagicMock()
    sm.get.return_value = None  # no cache, no skip
    payload = [
        _release("v2.4.0-a", body="Build: 470", prerelease=True),
    ]
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200, payload))
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)

    checker = UpdateChecker(sm)
    fired = []
    checker.update_available.connect(lambda info: fired.append(info))
    checker.check_sync(manual=True)
    assert len(fired) == 1
    assert fired[0]["tag_name"] == "v2.4.0-a"


def test_check_emits_no_update_when_local_is_latest(monkeypatch):
    sm = MagicMock()
    sm.get.return_value = None
    payload = [_release("v2.3.0-a", body="Build: 458", prerelease=True)]
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200, payload))
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)

    checker = UpdateChecker(sm)
    no_update_fired = []
    checker.no_update.connect(lambda: no_update_fired.append(True))
    checker.check_sync(manual=True)
    assert no_update_fired == [True]


def test_check_emits_failed_on_network_error(monkeypatch):
    sm = MagicMock()
    sm.get.return_value = None
    import requests
    def boom(*a, **k):
        raise requests.ConnectionError("dns failure")
    monkeypatch.setattr("requests.get", boom)
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: False)

    checker = UpdateChecker(sm)
    failures = []
    checker.check_failed.connect(lambda msg: failures.append(msg))
    checker.check_sync(manual=True)
    assert len(failures) == 1
    assert "dns failure" in failures[0] or "ConnectionError" in failures[0]


def test_check_respects_skipped_version_on_auto(monkeypatch):
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: {
        "update_skipped_version": "v2.4.0-a",
        "update_last_check_at": None,
        "update_last_check_result": None,
    }.get(key, default)
    payload = [_release("v2.4.0-a", body="Build: 470", prerelease=True)]
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200, payload))
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)

    checker = UpdateChecker(sm)
    fired_update = []
    fired_no = []
    checker.update_available.connect(lambda i: fired_update.append(i))
    checker.no_update.connect(lambda: fired_no.append(True))
    checker.check_sync(manual=False)
    assert fired_update == []
    assert fired_no == [True]


def test_manual_bypasses_skip_list(monkeypatch):
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: {
        "update_skipped_version": "v2.4.0-a",
        "update_last_check_at": None,
        "update_last_check_result": None,
    }.get(key, default)
    payload = [_release("v2.4.0-a", body="Build: 470", prerelease=True)]
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(200, payload))
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)

    checker = UpdateChecker(sm)
    fired_update = []
    checker.update_available.connect(lambda i: fired_update.append(i))
    checker.check_sync(manual=True)
    assert len(fired_update) == 1


def test_cache_replay_on_auto_within_ttl(monkeypatch):
    cached_release = {
        "tag_name": "v2.4.0-a",
        "body": "Build: 470\nNotes",
        "html_url": "https://example.com",
        "build_number": 470,
    }
    store = {"update_skipped_version": None}
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: store.get(key, default)
    sm.set.side_effect = lambda key, value: store.__setitem__(key, value)

    network_called = []
    def fake_get(*a, **k):
        network_called.append(True)
        return FakeResponse(200, [])
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)
    # Packaged build: head stamp is None and the source-run resolver never runs.
    monkeypatch.setattr("utils.build_info.is_source_run", lambda: False)

    # Seed the cache through the real writer (stamps live at the payload top level).
    update_checker._write_cache(sm, cached_release, None, "2.3.0-a", 458, None)

    checker = UpdateChecker(sm)
    fired = []
    checker.update_available.connect(lambda info: fired.append(info))
    checker.check_sync(manual=False)

    assert network_called == []
    assert len(fired) == 1
    assert fired[0]["tag_name"] == "v2.4.0-a"


def test_cache_invalidated_when_local_version_changed(monkeypatch):
    cached_release = {
        "tag_name": "v2.4.0-a",
        "body": "Build: 470",
        "html_url": "https://example.com",
        "build_number": 470,
    }
    store = {"update_skipped_version": None}
    sm = MagicMock()
    sm.get.side_effect = lambda key, default=None: store.get(key, default)
    sm.set.side_effect = lambda key, value: store.__setitem__(key, value)
    payload = [_release("v2.4.0-a", body="Build: 470", prerelease=True)]
    network_called = []
    def fake_get(*a, **k):
        network_called.append(True)
        return FakeResponse(200, payload)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("utils.build_flavor.is_beta", lambda: True)
    monkeypatch.setattr("utils.version.APP_VERSION", "2.3.0-a")
    monkeypatch.setattr("utils.build_info.build_number", lambda: 458)
    # Packaged build: the source-run resolver never runs, so the network
    # counter below sees exactly the one releases refetch.
    monkeypatch.setattr("utils.build_info.is_source_run", lambda: False)

    # Seed a cache stamped against a DIFFERENT local version/build.
    update_checker._write_cache(sm, cached_release, None, "2.2.0-a", 400, None)

    checker = UpdateChecker(sm)
    fired = []
    checker.update_available.connect(lambda info: fired.append(info))
    checker.check_sync(manual=False)

    # Cache was stamped against a different APP_VERSION → invalidated → network called.
    assert network_called == [True]
    assert len(fired) == 1
