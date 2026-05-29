"""Live, network-gated check that the real production manifest is reachable and
its structure matches what cc_patcher expects. Skipped unless CC_LIVE=1 to keep
the default suite offline. Does NOT need a token (manifests are public); the
download leg is covered by the unit tests + the cc-patch protocol probe.
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
