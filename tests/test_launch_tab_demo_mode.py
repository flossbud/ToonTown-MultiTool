"""Demo-mode fixtures gated behind TTMT_DEMO_LAUNCH_TAB env var."""
import os
from utils import launch_tab_demo_mode as dm


def test_unset_returns_none():
    if "TTMT_DEMO_LAUNCH_TAB" in os.environ:
        del os.environ["TTMT_DEMO_LAUNCH_TAB"]
    assert dm.get_demo_fixtures() is None


def test_populated_returns_seven_states():
    os.environ["TTMT_DEMO_LAUNCH_TAB"] = "populated"
    try:
        fix = dm.get_demo_fixtures()
        assert fix is not None
        assert set(t["state"] for t in fix["ttr"] + fix["cc"]) >= {
            "idle", "running", "logging_in", "need_2fa", "queued", "launching", "failed",
        }
    finally:
        del os.environ["TTMT_DEMO_LAUNCH_TAB"]


def test_empty_returns_zero_accounts():
    os.environ["TTMT_DEMO_LAUNCH_TAB"] = "empty"
    try:
        fix = dm.get_demo_fixtures()
        assert fix == {"ttr": [], "cc": []}
    finally:
        del os.environ["TTMT_DEMO_LAUNCH_TAB"]
