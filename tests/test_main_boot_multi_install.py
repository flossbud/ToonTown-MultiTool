"""Tests for the boot-time multi-install prompt logic."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _install(name):
    from services.wine_runtimes import WineInstall
    return WineInstall(
        exe_path=f"/x/{name}/CorporateClash.exe",
        launcher="bottles",
        prefix_path=f"/x/{name}",
        display_name=f"Bottles · {name}",
        metadata={"bottle_name": name},
    )


def test_prompt_skipped_when_zero_or_one_installs():
    from main import _should_prompt_for_cc_install
    assert _should_prompt_for_cc_install([], stored_signature="") is False
    assert _should_prompt_for_cc_install([_install("A")], stored_signature="") is False


def test_prompt_skipped_when_signature_matches():
    from main import _should_prompt_for_cc_install
    from services.wine_runtimes import install_signature
    a, b = _install("A"), _install("B")
    assert _should_prompt_for_cc_install(
        [a, b], stored_signature=install_signature(a)
    ) is False


def test_prompt_fires_when_ambiguous_and_no_match():
    from main import _should_prompt_for_cc_install
    a, b = _install("A"), _install("B")
    assert _should_prompt_for_cc_install([a, b], stored_signature="") is True
    assert _should_prompt_for_cc_install([a, b], stored_signature="nope") is True
