"""Pure-function version + build-number comparator for the update-check
flow. No I/O, no network, no Qt. Tag format: vMAJOR.MINOR.PATCH[-SUFFIX].
Stable = no suffix; beta = any suffix (-a, -b, -rc1, ...).

Comparison precedence: (major, minor, patch) tuple > suffix lexicographic
> build_number integer. The build-number tiebreaker covers re-released
tags and build-bumped-without-tag-bump edge cases.

Intentionally not PEP 440: our tag format is constrained enough that a
small comparator is clearer than pulling in `packaging` as a new runtime
dep across AppImage / Flatpak / Inno bundles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.]+))?$")


@dataclass(frozen=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    suffix: str  # "" for stable


def parse(tag: str) -> Optional[ParsedVersion]:
    if not tag:
        return None
    m = _TAG_RE.match(tag)
    if not m:
        return None
    return ParsedVersion(
        major=int(m.group(1)),
        minor=int(m.group(2)),
        patch=int(m.group(3)),
        suffix=m.group(4) or "",
    )


def is_beta_tag(tag: str) -> bool:
    parsed = parse(tag)
    return bool(parsed and parsed.suffix)


def compare(local: ParsedVersion, remote: ParsedVersion) -> int:
    lt = (local.major, local.minor, local.patch)
    rt = (remote.major, remote.minor, remote.patch)
    if lt != rt:
        return -1 if lt < rt else 1
    if local.suffix != remote.suffix:
        # Stable (no suffix) is newer than any pre-release suffix.
        # Within pre-release, use lexicographic order ("a" < "b" < "rc1").
        local_key = (0, local.suffix) if local.suffix else (1, "")
        remote_key = (0, remote.suffix) if remote.suffix else (1, "")
        return -1 if local_key < remote_key else 1
    return 0


def is_newer(
    local_ver: Optional[ParsedVersion],
    local_build: int,
    remote_ver: Optional[ParsedVersion],
    remote_build: int,
) -> bool:
    if local_ver is None or remote_ver is None:
        return False
    c = compare(local_ver, remote_ver)
    if c != 0:
        return c < 0
    return remote_build > local_build
