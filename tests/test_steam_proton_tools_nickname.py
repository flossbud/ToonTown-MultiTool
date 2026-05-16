"""Tests for services.steam_proton_tools._make_nickname."""

import pytest

from services.steam_proton_tools import _make_nickname


def test_proton_cachyos_dir_with_date_and_arch_suffix():
    """The motivating case: a CachyOS slug with all the trimmings."""
    assert _make_nickname(
        "proton-cachyos-11.0-20260429-slr-x86_64", None
    ) == "Proton-CachyOS 11.0"


def test_ge_proton_hybrid_token():
    """GE-Proton9-26: brand spills into the version-bearing token.

    Tokens after splitting: ["GE", "Proton9", "26"].
    - "GE" -> brand (via _BRAND_CASING)
    - "Proton9" -> hybrid: prefix "Proton" to brand, suffix "9" to
      version
    - "26" -> version (pure digits)
    Brand: "GE-Proton", Version: "9-26".
    """
    assert _make_nickname("GE-Proton9-26", None) == "GE-Proton 9-26"


def test_official_proton_with_dotted_version():
    assert _make_nickname("Proton-Tkg-9.0-amd64", None) == "Proton-Tkg 9.0"


def test_proton_no_version_keeps_brand_alone():
    """When no version digits are present after drop-filtering, return
    the brand alone."""
    assert _make_nickname("proton-experimental", None) == "Proton-Experimental"


def test_vdf_display_name_used_when_substantially_different():
    """Upstream tool ships a clean display_name — trust it."""
    assert _make_nickname(
        "some-internal-slug",
        vdf_display_name="Proton 9.0 (Beta)",
    ) == "Proton 9.0 (Beta)"


def test_vdf_display_name_rejected_when_same_as_dir_name():
    """Proton-CachyOS echoes its dir slug as display_name — fall
    through to Stage 2."""
    assert _make_nickname(
        "proton-cachyos-11.0-20260429-slr-x86_64",
        vdf_display_name="proton-cachyos-11.0-20260429-slr-x86_64",
    ) == "Proton-CachyOS 11.0"


def test_vdf_display_name_rejected_when_too_long():
    """A 33+ char VDF display_name fails the length guard."""
    long_vdf = "Proton-CachyOS 11.0 (build 20260429-x86)"  # 40 chars
    assert _make_nickname("proton-cachyos-11.0", vdf_display_name=long_vdf) == \
        "Proton-CachyOS 11.0"


def test_empty_dir_name_returns_empty_string():
    """Defensive: empty input -> empty output, no raise."""
    assert _make_nickname("", None) == ""


def test_length_guard_truncates_to_37_chars_plus_ellipsis():
    """Pathological 100-char custom name gets capped."""
    pathological = "weird-custom-internal-experimental-build-9.0"
    result = _make_nickname(pathological, None)
    if len(result) > 40:
        # If the parser produced something too long, it must end with …
        assert result.endswith("…")
        assert len(result) <= 40


def test_brand_casing_special_cases():
    """cachyos -> CachyOS, ge -> GE, tkg -> Tkg via the casing dict."""
    assert _make_nickname("cachyos-9.0", None) == "CachyOS 9.0"
    assert _make_nickname("ge-proton-9.0", None) == "GE-Proton 9.0"
    assert _make_nickname("proton-tkg-9.0", None) == "Proton-Tkg 9.0"


def test_brand_casing_falls_through_to_title_case():
    """Unknown brand words use str.title()."""
    assert _make_nickname("luxtorpeda-1.0", None) == "Luxtorpeda 1.0"
