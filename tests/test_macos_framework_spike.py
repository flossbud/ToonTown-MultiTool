import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import macos_framework_spike as spike


def test_format_provenance_is_stable_sorted_lines():
    info = {"sys.frozen": True, "platform.machine": "arm64", "sys.executable": "/x/py"}
    text = spike.format_provenance(info)
    # one "key = repr(value)" line per entry, in insertion order, 2-space indent
    assert text.splitlines() == [
        "  sys.frozen = True",
        "  platform.machine = 'arm64'",
        "  sys.executable = '/x/py'",
    ]


def test_provenance_has_required_keys():
    info = spike.provenance()
    for key in ("sys.executable", "sys.frozen", "platform.machine",
                "PYTHONFRAMEWORK", "libpython", "bundlePath"):
        assert key in info


def test_parse_xy_handles_ints_floats_and_spaces():
    assert spike._parse_xy("40,40") == (40.0, 40.0)
    assert spike._parse_xy(" 12.5 , 7 ") == (12.5, 7.0)
