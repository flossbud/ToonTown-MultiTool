"""Live, network-gated checks against CC's real production endpoints. Skipped
unless CC_LIVE=1 to keep the default suite offline.

The manifest-shape test needs no token (manifests are public). The end-to-end
download test additionally needs a CC launcher token in CC_TOKEN (the download
base lives behind the authenticated /metadata); it is the regression guard that
would catch CC changing its R2 object-key scheme out from under us.
"""
import os

import pytest

import services.cc_patcher as p

pytestmark = pytest.mark.skipif(
    os.environ.get("CC_LIVE") != "1", reason="set CC_LIVE=1 to run live network test"
)


def test_production_manifests_have_expected_shape():
    files = p.fetch_all_manifests("production", "windows")
    assert files, "production manifest is empty"
    for f in files:
        assert f["filePath"] and f["sha1"] and f["compressed_sha1"]
        assert f["_platform"] in ("windows", "resources")
    # both platform binaries and shared resources are present
    platforms = {f["_platform"] for f in files}
    assert platforms == {"windows", "resources"}


@pytest.mark.skipif(not os.environ.get("CC_TOKEN"),
                    reason="set CC_TOKEN=<launcher token> for the live download test")
def test_production_download_and_verify_one_of_each_platform():
    token = os.environ["CC_TOKEN"]
    base, server_name = p.resolve_download_server(token, "production")
    assert base
    files = p.fetch_all_manifests("production", "windows")
    # one windows binary + one resources asset must download and hash-match.
    for plat in ("windows", "resources"):
        entry = next(f for f in files if f["_platform"] == plat)
        data = p.fetch_verified(entry, base, server_name)  # raises on mismatch
        assert data
