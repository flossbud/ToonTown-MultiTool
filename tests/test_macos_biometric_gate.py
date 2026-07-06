"""Offscreen unit tests for the macOS biometric gate.

These exercise the enum-mapping logic - the part this module owns - by
monkeypatching the thin native seams (``_evaluate_policy`` /
``_can_evaluate_policy``). NO real Touch ID, NO real LocalAuthentication
framework, NO Qt, NO network. The native call itself is validated live on a
real Mac in Milestone 5.
"""

import subprocess
import sys

import pytest

from services import macos_biometric_gate as gate
from services.macos_biometric_gate import BiometricResult


# ── SUCCESS ──────────────────────────────────────────────────────────────────

def test_success_maps_from_true_none(monkeypatch):
    monkeypatch.setattr(gate, "_evaluate_policy", lambda reason: (True, None))
    assert gate.authenticate() is BiometricResult.SUCCESS


# ── CANCELLED (user / app / system cancel) ───────────────────────────────────

@pytest.mark.parametrize("code", [
    gate._LA_ERROR_USER_CANCEL,     # -2
    gate._LA_ERROR_APP_CANCEL,      # -9
    gate._LA_ERROR_SYSTEM_CANCEL,   # -4
])
def test_cancel_codes_map_to_cancelled(monkeypatch, code):
    monkeypatch.setattr(gate, "_evaluate_policy", lambda reason: (False, code))
    assert gate.authenticate() is BiometricResult.CANCELLED


def test_cancel_is_distinct_from_failure(monkeypatch):
    monkeypatch.setattr(gate, "_evaluate_policy",
                        lambda reason: (False, gate._LA_ERROR_USER_CANCEL))
    assert gate.authenticate() is not BiometricResult.FAILED


# ── UNAVAILABLE (no auth method configured -> caller fail-opens) ─────────────

def test_passcode_not_set_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(gate, "_evaluate_policy",
                        lambda reason: (False, gate._LA_ERROR_PASSCODE_NOT_SET))
    assert gate.authenticate() is BiometricResult.UNAVAILABLE


# ── FAILED (attempted-but-unsatisfied, unknown, and import-guard) ────────────

def test_authentication_failed_maps_to_failed(monkeypatch):
    monkeypatch.setattr(gate, "_evaluate_policy",
                        lambda reason: (False, gate._LA_ERROR_AUTHENTICATION_FAILED))
    assert gate.authenticate() is BiometricResult.FAILED


def test_unknown_error_code_maps_to_failed(monkeypatch):
    # An LAError code we do not special-case (e.g. biometry lockout / invalid
    # context / some future code) must collapse to FAILED, never leak through.
    monkeypatch.setattr(gate, "_evaluate_policy", lambda reason: (False, -99999))
    assert gate.authenticate() is BiometricResult.FAILED


def test_none_error_code_without_success_maps_to_failed(monkeypatch):
    # (False, None) is exactly what the import guard returns; it must be FAILED,
    # never confused with the (True, None) success case.
    monkeypatch.setattr(gate, "_evaluate_policy", lambda reason: (False, None))
    assert gate.authenticate() is BiometricResult.FAILED


def test_import_guard_returns_failed_when_binding_absent(monkeypatch):
    # Force the lazy `import LocalAuthentication` to raise ImportError by shadowing
    # the module to None, then drive the REAL _evaluate_policy (not a stub). It
    # must degrade to (False, None) -> FAILED, so the module works with no
    # framework installed.
    monkeypatch.setitem(sys.modules, "LocalAuthentication", None)
    assert gate._evaluate_policy("whatever") == (False, None)
    monkeypatch.setattr(gate, "_evaluate_policy", lambda reason: (False, None))
    assert gate.authenticate() is BiometricResult.FAILED


# ── Reason string ────────────────────────────────────────────────────────────

def test_default_reason_used_when_none_given(monkeypatch):
    seen = {}

    def _capture(reason):
        seen["reason"] = reason
        return (True, None)

    monkeypatch.setattr(gate, "_evaluate_policy", _capture)
    gate.authenticate()
    assert seen["reason"] == "Unlock your ToonTown MultiTool accounts"


def test_default_reason_used_for_empty_string(monkeypatch):
    seen = {}

    def _capture(reason):
        seen["reason"] = reason
        return (True, None)

    monkeypatch.setattr(gate, "_evaluate_policy", _capture)
    gate.authenticate("")
    assert seen["reason"] == "Unlock your ToonTown MultiTool accounts"


def test_custom_reason_is_passed_through(monkeypatch):
    seen = {}

    def _capture(reason):
        seen["reason"] = reason
        return (True, None)

    monkeypatch.setattr(gate, "_evaluate_policy", _capture)
    gate.authenticate("Please confirm it's you")
    assert seen["reason"] == "Please confirm it's you"


# ── can_authenticate() reflects the (mocked) canEvaluatePolicy ───────────────

def test_can_authenticate_true(monkeypatch):
    monkeypatch.setattr(gate, "_can_evaluate_policy", lambda: True)
    assert gate.can_authenticate() is True


def test_can_authenticate_false(monkeypatch):
    monkeypatch.setattr(gate, "_can_evaluate_policy", lambda: False)
    assert gate.can_authenticate() is False


def test_can_authenticate_false_when_binding_absent(monkeypatch):
    # Real _can_evaluate_policy with the framework shadowed away -> False.
    monkeypatch.setitem(sys.modules, "LocalAuthentication", None)
    assert gate._can_evaluate_policy() is False


# ── Enum surface ─────────────────────────────────────────────────────────────

def test_biometric_result_has_exactly_four_outcomes():
    assert {r.name for r in BiometricResult} == {
        "SUCCESS", "CANCELLED", "FAILED", "UNAVAILABLE"
    }


# ── Import hygiene: zero side effects, no Qt, no eager native import ──────────

def test_module_imports_with_zero_side_effects_and_no_qt():
    # A fresh interpreter imports the gate and asserts it pulled in neither Qt
    # nor the LocalAuthentication binding at load time (both must be lazy). Runs
    # on any host: on macOS the framework IS installed, so a non-lazy import
    # would show up here.
    code = (
        "import sys; import services.macos_biometric_gate as g; "
        "assert 'LocalAuthentication' not in sys.modules, 'eager LA import'; "
        "assert not any(m == 'PySide6' or m.startswith('PySide6.') for m in sys.modules), 'Qt imported'; "
        "print('IMPORT_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "IMPORT_OK" in result.stdout, result.stdout
