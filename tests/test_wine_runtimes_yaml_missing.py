"""When PyYAML is unavailable, the bottle.yml/Lutris parsers must degrade
loudly, not silently.

Regression context: the Flatpak shipped without PyYAML, so `import yaml`
raised ImportError inside the sandbox. Both parsers swallowed it in a bare
`except Exception`, so the failure was invisible -- the Corporate Clash bottle
name silently fell back to the hyphenated directory basename and bottles-cli
reported `Bottle Corporate-Clash not found`. These tests pin the new behavior:
a missing PyYAML returns the unparseable sentinel AND logs a clear marker.
"""

import sys

import pytest

from services import wine_runtimes


@pytest.fixture
def yaml_unavailable(monkeypatch):
    """Force `import yaml` to raise ImportError, as in a PyYAML-less sandbox.

    Setting a module entry to None makes the import machinery raise ImportError
    for that name (the documented way to simulate a missing module).
    """
    monkeypatch.setitem(sys.modules, "yaml", None)


def test_read_bottle_name_logs_and_returns_none_without_pyyaml(
    tmp_path, yaml_unavailable, capsys
):
    bottle_yml = tmp_path / "bottle.yml"
    bottle_yml.write_text("Name: Corporate Clash\n", encoding="utf-8")

    result = wine_runtimes._read_bottle_name(str(tmp_path))

    assert result is None
    out = capsys.readouterr().out
    assert "PyYAML unavailable" in out


def test_parse_lutris_yaml_logs_and_returns_sentinel_without_pyyaml(
    tmp_path, yaml_unavailable, capsys
):
    game_yml = tmp_path / "game.yml"
    game_yml.write_text("name: CC\ngame:\n  prefix: /some/prefix\n", encoding="utf-8")

    result = wine_runtimes._parse_lutris_yaml(str(game_yml))

    assert result == (None, None, None)
    out = capsys.readouterr().out
    assert "PyYAML unavailable" in out


def test_read_bottle_name_still_reads_name_when_pyyaml_present(tmp_path):
    """Sanity: with PyYAML available (the normal case) the Name is returned."""
    pytest.importorskip("yaml")
    bottle_yml = tmp_path / "bottle.yml"
    bottle_yml.write_text("Name: Corporate Clash\n", encoding="utf-8")

    assert wine_runtimes._read_bottle_name(str(tmp_path)) == "Corporate Clash"
