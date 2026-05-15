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


def test_maybe_prompt_writes_settings_on_accept(monkeypatch):
    """When the dialog is accepted, all three settings keys are written."""
    from main import _maybe_prompt_for_cc_install
    from services.wine_runtimes import install_signature

    installs = [_install("A"), _install("B")]
    # _maybe_prompt_for_cc_install imports these lazily, so we patch the
    # source modules (where `from X import Y` actually resolves), not `main`.
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs",
        lambda: installs, raising=False,
    )

    class _FakeDialog:
        Accepted = 1
        def __init__(self, *a, **kw): pass
        def exec(self): return self.Accepted
        def selected_install(self): return installs[1]

    monkeypatch.setattr(
        "utils.widgets.cc_install_picker.CCInstallPickerDialog",
        _FakeDialog, raising=False,
    )

    stored = {}
    class _Settings:
        def get(self, k, d=""):
            return stored.get(k, d)
        def set(self, k, v):
            stored[k] = v

    class _Window:
        settings_tab = None  # No tab; refresh path no-ops

    _maybe_prompt_for_cc_install(_Window(), _Settings())
    expected_sig = install_signature(installs[1])
    assert stored["cc_engine_install_signature"] == expected_sig
    assert stored["cc_engine_dir"].endswith("/B")


def test_maybe_prompt_skips_when_unambiguous(monkeypatch):
    """When state isn't ambiguous, dialog is never instantiated."""
    from main import _maybe_prompt_for_cc_install
    installs = [_install("only")]
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs",
        lambda: installs, raising=False,
    )

    def _no_dialog(*a, **kw):
        raise AssertionError("Dialog should not be constructed")
    monkeypatch.setattr(
        "utils.widgets.cc_install_picker.CCInstallPickerDialog",
        _no_dialog, raising=False,
    )

    class _Settings:
        def get(self, k, d=""): return ""
        def set(self, k, v): pass

    class _Window:
        settings_tab = None

    _maybe_prompt_for_cc_install(_Window(), _Settings())
