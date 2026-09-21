"""download_pose classifies failures so the prefetcher can tell a stalled
origin (breaker event) from a bad DNA (not one)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import io
import socket
import urllib.error

import pytest

from utils.rendition_poses import BREAKER_KINDS, DownloadError, download_pose


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_success_returns_bytes():
    def opener(req, timeout, context):
        assert "74000101aa/head/512x512.png" in req.full_url
        return _Resp(b"\x89PNGdata")
    assert download_pose("74000101aa", "head", opener=opener) == b"\x89PNGdata"


@pytest.mark.parametrize("exc, kind, status", [
    (socket.timeout("read timed out"), "timeout", None),
    (TimeoutError("read timed out"), "timeout", None),
    (urllib.error.HTTPError("u", 524, "timeout", {}, None), "server", 524),
    (urllib.error.HTTPError("u", 503, "busy", {}, None), "server", 503),
    (urllib.error.HTTPError("u", 404, "nope", {}, None), "client", 404),
    (urllib.error.HTTPError("u", 400, "bad", {}, None), "client", 400),
    (urllib.error.URLError("dns"), "other", None),
    (OSError("reset"), "other", None),
])
def test_failures_are_classified(exc, kind, status):
    def opener(req, timeout, context):
        raise exc
    with pytest.raises(DownloadError) as ei:
        download_pose("74000101aa", "head", opener=opener)
    assert ei.value.kind == kind
    assert ei.value.status == status


def test_only_client_errors_are_not_breaker_events():
    assert BREAKER_KINDS == {"timeout", "server", "other"}
    assert "client" not in BREAKER_KINDS


def test_empty_body_is_a_server_error():
    def opener(req, timeout, context):
        return _Resp(b"")
    with pytest.raises(DownloadError) as ei:
        download_pose("74000101aa", "head", opener=opener)
    assert ei.value.kind == "server"
