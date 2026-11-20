"""Resumable update download: partial files, Range requests, verification."""
import hashlib

import pytest
import requests

from utils import update_download as dl

DATA = bytes(range(256)) * 400            # 102,400 bytes
URL = "https://example.invalid/Setup.exe"


def _asset(data=DATA, digest=True):
    asset = {"name": "Setup.exe", "size": len(data), "browser_download_url": URL}
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return asset


class _Response:
    def __init__(self, status, body, headers=None, fail_after=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self._fail_after = fail_after

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=1):
        sent = 0
        for start in range(0, len(self._body), chunk_size):
            if self._fail_after is not None and sent >= self._fail_after:
                raise requests.ConnectionError("dropped")
            chunk = self._body[start:start + chunk_size]
            sent += len(chunk)
            yield chunk


class _Server:
    """Serves DATA; honours Range unless told not to."""

    def __init__(self, data=DATA, honour_range=True, fail_after=None):
        self.data = data
        self.honour_range = honour_range
        self.fail_after = fail_after
        self.requests = []

    def get(self, url, stream=True, headers=None, timeout=None):
        headers = headers or {}
        self.requests.append(dict(headers))
        start = 0
        if "Range" in headers and self.honour_range:
            start = int(headers["Range"].split("=")[1].rstrip("-"))
            if start >= len(self.data):
                return _Response(416, b"")
            return _Response(206, self.data[start:], {
                "Content-Range": f"bytes {start}-{len(self.data) - 1}/{len(self.data)}"},
                fail_after=self.fail_after)
        return _Response(200, self.data, {"Content-Length": str(len(self.data))},
                         fail_after=self.fail_after)


def test_a_whole_download_lands_at_its_final_name(tmp_path):
    seen = []
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=_Server(),
                            on_progress=lambda r, t: seen.append((r, t)))
    assert reason == "" and path == str(tmp_path / "Setup.exe")
    assert (tmp_path / "Setup.exe").read_bytes() == DATA
    assert not (tmp_path / "Setup.exe.part").exists()
    assert seen[-1] == (len(DATA), len(DATA))


def test_a_dropped_connection_keeps_the_partial_file(tmp_path):
    server = _Server(fail_after=40_000)
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=server)
    assert path is None and reason == dl.REASON_NETWORK
    partial = tmp_path / "Setup.exe.part"
    assert partial.exists() and 0 < partial.stat().st_size < len(DATA)
    assert dl.partial_size(_asset(), str(tmp_path)) == partial.stat().st_size


def test_the_next_try_resumes_at_the_byte_it_stopped(tmp_path):
    dl.fetch(_asset(), out_dir=str(tmp_path), session=_Server(fail_after=40_000))
    have = (tmp_path / "Setup.exe.part").stat().st_size
    server = _Server()
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=server)
    assert reason == "" and (tmp_path / "Setup.exe").read_bytes() == DATA
    assert server.requests == [{"Range": f"bytes={have}-"}]


def test_a_server_that_ignores_the_range_starts_over(tmp_path):
    (tmp_path / "Setup.exe.part").write_bytes(DATA[:5000])
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path),
                            session=_Server(honour_range=False))
    assert reason == "" and (tmp_path / "Setup.exe").read_bytes() == DATA


def test_a_complete_partial_file_is_just_checked_and_renamed(tmp_path):
    (tmp_path / "Setup.exe.part").write_bytes(DATA)
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=_Server())
    assert reason == "" and (tmp_path / "Setup.exe").read_bytes() == DATA


def test_an_already_downloaded_file_is_not_fetched_again(tmp_path):
    (tmp_path / "Setup.exe").write_bytes(DATA)
    server = _Server()
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=server)
    assert reason == "" and server.requests == []


def test_wrong_bytes_are_thrown_away(tmp_path):
    wrong = bytes(reversed(DATA))
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=_Server(data=wrong))
    assert path is None and reason == dl.REASON_VERIFY
    assert not (tmp_path / "Setup.exe").exists()
    assert not (tmp_path / "Setup.exe.part").exists()


def test_a_short_stream_is_a_network_failure_not_a_bad_file(tmp_path):
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path),
                            session=_Server(data=DATA[:60_000], honour_range=False))
    assert path is None and reason == dl.REASON_NETWORK
    assert (tmp_path / "Setup.exe.part").stat().st_size == 60_000


def test_a_partial_file_larger_than_the_asset_is_not_trusted(tmp_path):
    (tmp_path / "Setup.exe.part").write_bytes(DATA + b"extra")
    server = _Server()
    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=server)
    assert reason == "" and server.requests == [{}]


def test_cancelling_stops_and_keeps_what_arrived(tmp_path):
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    path, reason = dl.fetch(_asset(), out_dir=str(tmp_path), session=_Server(),
                            cancelled=cancelled)
    assert path is None and reason == dl.REASON_CANCELLED
    assert (tmp_path / "Setup.exe.part").exists()


def test_size_alone_decides_when_the_feed_has_no_digest(tmp_path):
    asset = _asset(digest=False)
    (tmp_path / "Setup.exe").write_bytes(bytes(len(DATA)))
    assert dl.file_matches(str(tmp_path / "Setup.exe"), asset)
    (tmp_path / "Setup.exe").write_bytes(b"short")
    assert not dl.file_matches(str(tmp_path / "Setup.exe"), asset)


def test_discard_removes_both_files(tmp_path):
    (tmp_path / "Setup.exe").write_bytes(DATA)
    (tmp_path / "Setup.exe.part").write_bytes(DATA[:10])
    dl.discard(_asset(), str(tmp_path))
    assert list(tmp_path.glob("Setup.exe*")) == []


def test_the_downloader_reports_on_the_gui_thread(qapp, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(requests, "get", _Server().get)
    downloader = dl.UpdateDownloader(out_dir=str(tmp_path))
    finished, failed = [], []
    downloader.finished.connect(finished.append)
    downloader.failed.connect(failed.append)
    assert downloader.start(_asset()) is True
    assert downloader.start(_asset()) is False          # one at a time
    deadline = time.monotonic() + 10
    while not (finished or failed) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert finished == [str(tmp_path / "Setup.exe")] and failed == []
    assert not downloader.is_running()


def test_the_downloader_reports_a_failure(qapp, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(requests, "get", _Server(fail_after=1000).get)
    downloader = dl.UpdateDownloader(out_dir=str(tmp_path))
    finished, failed = [], []
    downloader.finished.connect(finished.append)
    downloader.failed.connect(failed.append)
    downloader.start(_asset())
    deadline = time.monotonic() + 10
    while not (finished or failed) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert finished == [] and failed == [dl.REASON_NETWORK]
