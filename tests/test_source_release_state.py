"""Classifier/resolver tests: fake git runner + fake API, no subprocess,
no network."""
from utils.source_release_state import (
    ReleaseState,
    classify,
    head_sha,
    resolve_release_commit,
)

SHA = "a" * 40
OTHER = "b" * 40


def _runner(table):
    """Fake runner: maps ' '.join(args) -> (rc, stdout). Unknown -> error."""
    calls = []

    def run(args, timeout=5.0):
        calls.append(list(args))
        return table.get(" ".join(args), (-1, ""))

    run.calls = calls
    return run


def test_object_absent_is_unprovable():
    # Real git returns 128 for a missing/unpeelable object (not 1).
    run = _runner({f"cat-file -e {SHA}^{{commit}}": (128, "")})
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE


def test_classify_rejects_non_sha_input():
    def boom(args, timeout=5.0):
        raise AssertionError("non-sha must never reach git argv")

    assert classify("--upload-pack=evil", run=boom) is ReleaseState.UNPROVABLE
    assert classify("", run=boom) is ReleaseState.UNPROVABLE
    assert classify("HEAD", run=boom) is ReleaseState.UNPROVABLE


def test_release_ancestor_of_head_is_at_or_past():
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (0, ""),
    })
    assert classify(SHA, run=run) is ReleaseState.AT_OR_PAST


def test_head_ancestor_of_release_is_behind():
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (0, ""),
    })
    assert classify(SHA, run=run) is ReleaseState.BEHIND


def test_double_no_on_full_repo_is_divergent():
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (1, ""),
        "rev-parse --is-shallow-repository": (0, "false\n"),
    })
    assert classify(SHA, run=run) is ReleaseState.DIVERGENT


def test_double_no_on_shallow_repo_is_unprovable():
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (1, ""),
        "rev-parse --is-shallow-repository": (0, "true\n"),
    })
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE


def test_strict_rc_interpretation_unexpected_rc_is_unprovable():
    # rc 2 (or the runner's -1 error tuple) on EITHER ancestor check is an
    # error, never a "no".
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (2, ""),
    })
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (-1, ""),
    })
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE


def test_shallow_garbage_output_is_unprovable():
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (1, ""),
        "rev-parse --is-shallow-repository": (0, "maybe\n"),
    })
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE


def test_shallow_check_rc_failure_is_unprovable():
    # The rc==0 guard is load-bearing: a failing shallow check with
    # plausible stdout must never grant DIVERGENT (a suppression state).
    run = _runner({
        f"cat-file -e {SHA}^{{commit}}": (0, ""),
        f"merge-base --is-ancestor {SHA} HEAD": (1, ""),
        f"merge-base --is-ancestor HEAD {SHA}": (1, ""),
        "rev-parse --is-shallow-repository": (1, "false\n"),
    })
    assert classify(SHA, run=run) is ReleaseState.UNPROVABLE


def test_resolver_prefers_local_tag_no_api():
    api_calls = []

    def api_get(url):
        api_calls.append(url)
        return None

    run = _runner({
        "rev-parse --verify --quiet refs/tags/v1.2.3^{commit}": (0, f"{SHA}\n"),
    })
    assert resolve_release_commit("v1.2.3", api_get, run=run) == SHA
    assert api_calls == []  # zero network when the tag is local


def test_resolver_api_lightweight_tag():
    run = _runner({})  # local lookup fails (error tuple)

    def api_get(url):
        assert url.endswith("/git/ref/tags/v1.2.3")
        return {"object": {"type": "commit", "sha": SHA}}

    assert resolve_release_commit("v1.2.3", api_get, run=run) == SHA


def test_resolver_api_annotated_tag_chain():
    responses = {
        "/git/ref/tags/v1.2.3": {"object": {"type": "tag", "sha": OTHER}},
        f"/git/tags/{OTHER}": {"object": {"type": "commit", "sha": SHA}},
    }

    def api_get(url):
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                return payload
        return None

    run = _runner({})
    assert resolve_release_commit("v1.2.3", api_get, run=run) == SHA


def test_resolver_api_cycle_and_depth_exhaustion_return_none():
    # A tag object that dereferences to itself: bounded deref must give up.
    def api_get(url):
        return {"object": {"type": "tag", "sha": OTHER}}

    run = _runner({})
    assert resolve_release_commit("v1.2.3", api_get, run=run) is None


def test_resolver_deref_budget_max_four_http_calls():
    # 1 ref lookup + at most 3 derefs: a 4-deep tag chain stops WITHOUT a
    # wasteful 4th deref request.
    chain = ["s1", "s2", "s3", "s4"]
    calls = []

    def api_get(url):
        calls.append(url)
        if url.endswith("/git/ref/tags/v1.2.3"):
            return {"object": {"type": "tag", "sha": chain[0]}}
        for i, sha in enumerate(chain):
            if url.endswith(f"/git/tags/{sha}"):
                nxt = chain[i + 1] if i + 1 < len(chain) else "s5"
                return {"object": {"type": "tag", "sha": nxt}}
        return None

    assert resolve_release_commit("v1.2.3", api_get, run=_runner({})) is None
    assert len(calls) == 4  # ref + 3 derefs, never a 4th deref


def test_resolver_three_deref_chain_resolves():
    chain = {
        "/git/ref/tags/v1.2.3": {"object": {"type": "tag", "sha": "s1"}},
        "/git/tags/s1": {"object": {"type": "tag", "sha": "s2"}},
        "/git/tags/s2": {"object": {"type": "tag", "sha": "s3"}},
        "/git/tags/s3": {"object": {"type": "commit", "sha": SHA}},
    }

    def api_get(url):
        for suffix, payload in chain.items():
            if url.endswith(suffix):
                return payload
        return None

    assert resolve_release_commit("v1.2.3", api_get, run=_runner({})) == SHA


def test_resolver_api_malformed_and_error_return_none():
    run = _runner({})
    assert resolve_release_commit("v1.2.3", lambda url: None, run=run) is None
    assert resolve_release_commit("v1.2.3", lambda url: {"x": 1}, run=run) is None
    assert resolve_release_commit(
        "v1.2.3", lambda url: {"object": {"type": "blob", "sha": SHA}},
        run=run) is None


def test_resolver_url_encodes_tag():
    seen = []

    def api_get(url):
        seen.append(url)
        return None

    run = _runner({})
    resolve_release_commit("v1.2.3-rc+x", api_get, run=run)
    assert seen and "v1.2.3-rc%2Bx" in seen[0]


def test_head_sha_live_no_caching():
    outputs = iter([f"{SHA}\n", f"{OTHER}\n"])

    def run(args, timeout=5.0):
        assert args == ["rev-parse", "HEAD"]
        return (0, next(outputs))

    assert head_sha(run=run) == SHA
    assert head_sha(run=run) == OTHER  # second call re-queries


def test_head_sha_failure_returns_none():
    assert head_sha(run=lambda a, timeout=5.0: (-1, "")) is None
