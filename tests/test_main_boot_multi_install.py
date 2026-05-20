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
    assert _should_prompt_for_cc_install([], stored_signature="", stored_set_hash="") is False
    assert _should_prompt_for_cc_install([_install("A")], stored_signature="", stored_set_hash="") is False


def test_prompt_skipped_when_signature_matches_and_set_unchanged():
    from main import _should_prompt_for_cc_install
    from services.wine_runtimes import install_signature, install_set_hash
    a, b = _install("A"), _install("B")
    assert _should_prompt_for_cc_install(
        [a, b],
        stored_signature=install_signature(a),
        stored_set_hash=install_set_hash([a, b]),
    ) is False


def test_prompt_fires_when_ambiguous_and_no_match():
    from main import _should_prompt_for_cc_install
    from services.wine_runtimes import install_set_hash
    a, b = _install("A"), _install("B")
    set_hash = install_set_hash([a, b])
    assert _should_prompt_for_cc_install(
        [a, b], stored_signature="", stored_set_hash=set_hash
    ) is True
    assert _should_prompt_for_cc_install(
        [a, b], stored_signature="nope", stored_set_hash=set_hash
    ) is True


def test_prompt_fires_when_install_set_changed(monkeypatch):
    """User had two installs and picked one. Later, a third install appears.
    Stored signature still matches the previously-picked install, but the
    install set as a whole has changed since last seen — fire the prompt."""
    from main import _should_prompt_for_cc_install
    from services.wine_runtimes import install_signature, install_set_hash
    a, b = _install("A"), _install("B")
    old_set_hash = install_set_hash([a, b])
    c = _install("C")
    # Stored sig matches A, stored set_hash reflects [a, b], but current
    # discovery returns [a, b, c].
    assert _should_prompt_for_cc_install(
        [a, b, c],
        stored_signature=install_signature(a),
        stored_set_hash=old_set_hash,
    ) is True


def test_prompt_fires_when_legacy_settings_have_no_set_hash():
    """Migration: a user upgrading from a TTMT build without this feature has
    no stored set hash. If they're in multi-install state with a matching
    signature, fire the prompt once so they see all detected installs."""
    from main import _should_prompt_for_cc_install
    from services.wine_runtimes import install_signature
    a, b = _install("A"), _install("B")
    assert _should_prompt_for_cc_install(
        [a, b],
        stored_signature=install_signature(a),
        stored_set_hash="",  # legacy: never written before
    ) is True


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


def test_maybe_prompt_writes_set_hash_after_acceptance(monkeypatch):
    """After the user picks, the current install-set hash is recorded so the
    next boot won't re-prompt for the same set."""
    from main import _maybe_prompt_for_cc_install
    from services.wine_runtimes import install_set_hash

    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs",
        lambda: installs, raising=False,
    )

    class _FakeDialog:
        Accepted = 1
        def __init__(self, *a, **kw): pass
        def exec(self): return self.Accepted
        def selected_install(self): return installs[0]

    monkeypatch.setattr(
        "utils.widgets.cc_install_picker.CCInstallPickerDialog",
        _FakeDialog, raising=False,
    )

    stored = {}
    class _Settings:
        def get(self, k, d=""): return stored.get(k, d)
        def set(self, k, v): stored[k] = v

    class _Window:
        settings_tab = None

    _maybe_prompt_for_cc_install(_Window(), _Settings())
    assert stored["cc_engine_install_set_hash"] == install_set_hash(installs)


def test_maybe_prompt_writes_set_hash_even_when_no_prompt_fires(monkeypatch):
    """When the install set is unchanged and signature matches, no prompt
    fires — but the hash is rewritten anyway so it stays current. Idempotent."""
    from main import _maybe_prompt_for_cc_install
    from services.wine_runtimes import install_signature, install_set_hash

    installs = [_install("A"), _install("B")]
    monkeypatch.setattr(
        "services.wine_runtimes.discover_cc_installs",
        lambda: installs, raising=False,
    )

    def _no_dialog(*a, **kw):
        raise AssertionError("Dialog should not be constructed when set unchanged")
    monkeypatch.setattr(
        "utils.widgets.cc_install_picker.CCInstallPickerDialog",
        _no_dialog, raising=False,
    )

    stored = {
        "cc_engine_install_signature": install_signature(installs[0]),
        "cc_engine_install_set_hash": install_set_hash(installs),
    }
    class _Settings:
        def get(self, k, d=""): return stored.get(k, d)
        def set(self, k, v): stored[k] = v

    class _Window:
        settings_tab = None

    _maybe_prompt_for_cc_install(_Window(), _Settings())
    # Hash still reflects current set (idempotent write).
    assert stored["cc_engine_install_set_hash"] == install_set_hash(installs)


def test_maybe_prompt_skips_when_unambiguous(monkeypatch):
    """When state isn't ambiguous (single install), dialog is never
    instantiated."""
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
