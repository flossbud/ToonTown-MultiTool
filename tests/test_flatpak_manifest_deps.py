"""Guard: the Flatpak manifest must bundle every Linux runtime dependency.

The motivating bug: the Flatpak `python-deps` module pip-installs a hardcoded
package list rather than `-r requirements.txt`. When `requirements.txt` gained
`PyYAML` (Linux-only, for parsing Bottles/Lutris `bottle.yml`), the manifest
list was not updated. Inside the sandbox `import yaml` then raised ImportError,
which `services.wine_runtimes._read_bottle_name` silently swallowed -- so the
Corporate Clash bottle name fell back to the hyphenated directory basename
("Corporate-Clash") and `bottles-cli` reported `Bottle Corporate-Clash not
found`. Source/AppImage builds bundled PyYAML, so only the Flatpak broke.

This test cross-checks the two lists so a missing bundled dependency fails CI
instead of silently degrading a launch path. It is one-directional: the
manifest may carry extras the bare requirements file omits (e.g. `evdev`, an
input backend only needed inside the KDE runtime), but it must not be MISSING
any Linux runtime requirement.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
MANIFEST = os.path.join(ROOT, "flatpak", "io.github.flossbud.ToonTownMultiTool.yml")

# Requirements that are intentionally NOT bundled in the Flatpak:
#   pywin32    -- Windows-only (carries a sys_platform == "win32" marker).
#   pyinstaller -- build-time only; the Flatpak runs the source tree directly
#                  via launcher.sh and never freezes a binary.
_NOT_BUNDLED = {"pywin32", "pyinstaller"}


def _canonical(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of -_. collapse to a single -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pkg_name(spec: str) -> str:
    """Strip version specifiers / extras / markers from a requirement token."""
    # Drop environment markers and version constraints.
    spec = spec.split(";")[0]
    spec = re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0]
    return _canonical(spec.strip())


def _linux_runtime_requirements() -> set[str]:
    """Canonical package names from requirements.txt that apply to a Linux
    runtime (excludes win32-marked and build-only packages)."""
    names: set[str] = set()
    with open(REQUIREMENTS, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if 'sys_platform == "win32"' in line:
                continue
            name = _pkg_name(line)
            if name and name not in _NOT_BUNDLED:
                names.add(name)
    return names


def _manifest_pip_packages() -> set[str]:
    """Canonical package names from the manifest's python-deps pip3 command."""
    with open(MANIFEST, encoding="utf-8") as f:
        text = f.read()
    # The pip3 install invocation spans several wrapped YAML lines after the
    # `- pip3 install --prefix=/app --no-build-isolation` entry. Grab from that
    # marker to the next module/list boundary, then tokenize.
    marker = "pip3 install"
    start = text.index(marker)
    # Stop at the start of the next top-level list item ("  - name:") after it.
    tail = text[start:]
    end = tail.find("\n  - name:")
    block = tail if end == -1 else tail[:end]
    names: set[str] = set()
    for tok in block.split():
        # Package tokens are the quoted/bare specs; skip flags and the verb.
        cleaned = tok.strip().strip('"').strip("'")
        if not cleaned or cleaned.startswith("-") or cleaned in {"pip3", "install"}:
            continue
        name = _pkg_name(cleaned)
        if name:
            names.add(name)
    return names


def test_flatpak_bundles_all_linux_runtime_requirements():
    required = _linux_runtime_requirements()
    bundled = _manifest_pip_packages()
    missing = required - bundled
    assert not missing, (
        "Flatpak manifest python-deps is missing Linux runtime dependencies "
        f"declared in requirements.txt: {sorted(missing)}. Add them to the "
        "pip3 install line in "
        "flatpak/io.github.flossbud.ToonTownMultiTool.yml."
    )


def test_pyyaml_specifically_is_bundled():
    """Direct regression assertion for the bug that motivated this guard."""
    assert "pyyaml" in _manifest_pip_packages(), (
        "PyYAML must be bundled in the Flatpak; without it bottle.yml parsing "
        "silently fails and Corporate Clash launches with the wrong bottle name."
    )
