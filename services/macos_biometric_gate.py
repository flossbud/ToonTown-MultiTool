"""Single-prompt biometric / password gate for the macOS credential vault.

The macOS vault (``utils/macos_credential_vault.py``) is deliberately
gate-agnostic: it owns the crypto, not the auth prompt. This module is the ONE
prompt that guards it. It wraps ``LAContext.evaluatePolicy`` with
``LAPolicy.deviceOwnerAuthentication`` so the operating system shows Touch ID (or
Apple Watch) when one is enrolled and otherwise the Mac account password - a
single prompt, never two. We never use the biometrics-only policy variant; the
whole point is that biometrics *replace* the password when available and the OS
falls back to the password on its own.

Outcomes collapse to :class:`BiometricResult`:

- ``SUCCESS``     - the policy evaluated true; unlock the session.
- ``CANCELLED``   - user / app / system cancel (retriable, not a failure).
- ``FAILED``      - authentication was attempted but not satisfied, plus any
                    other error and the import-guard fallback.
- ``UNAVAILABLE`` - no auth method configured at all (``LAErrorPasscodeNotSet``).
                    This is the ONLY "no auth possible" case; the caller
                    fail-opens and reads the vault without a gate.

Design for testability + correctness: the raw native call lives in the thin
private :func:`_evaluate_policy` (and :func:`_can_evaluate_policy`); the public
functions only map its ``(success, error_code)`` result to the enum. Tests
monkeypatch those seams and exercise the mapping. The native call itself is
validated live on a real Mac in Milestone 5.

The ``LocalAuthentication`` binding is imported LAZILY inside the native seams
and guarded, so this module imports on any platform (Linux/Windows CI included)
with zero side effects, no Qt, and no network - even when the framework is
absent. A missing binding maps to ``FAILED`` with a diagnostic.
"""

from __future__ import annotations

import enum
import os
import threading

# LAPolicy.deviceOwnerAuthentication - Touch ID / Apple Watch when enrolled,
# else the Mac account password (the OS handles that fallback itself). This is
# NOT the biometrics-only variant (value 1); using 2 is what makes it exactly
# one prompt with password fallback.
_POLICY_DEVICE_OWNER_AUTH = 2

# LAError codes we branch on. Hardcoded (stable macOS SDK constants) so the
# enum-mapping logic is fully defined even when the LocalAuthentication binding
# is absent - the mapping is what the offscreen tests cover.
_LA_ERROR_AUTHENTICATION_FAILED = -1
_LA_ERROR_USER_CANCEL = -2
_LA_ERROR_SYSTEM_CANCEL = -4
_LA_ERROR_PASSCODE_NOT_SET = -5
_LA_ERROR_APP_CANCEL = -9

# User, app, and system cancels are all "not now", distinct from a real failure.
_CANCEL_CODES = frozenset({
    _LA_ERROR_USER_CANCEL,
    _LA_ERROR_APP_CANCEL,
    _LA_ERROR_SYSTEM_CANCEL,
})

# Default localized reason shown in the system prompt.
_DEFAULT_REASON = "Unlock your ToonTown MultiTool accounts"


def _dbg(msg: str) -> None:
    """Opt-in diagnostic. Quiet unless ``TTMT_BIOMETRIC_TRACE`` is set, so import
    and normal operation have no side effects. Never raises."""
    if os.environ.get("TTMT_BIOMETRIC_TRACE"):
        try:
            print(msg)
        except Exception:
            pass


class BiometricResult(str, enum.Enum):
    """Outcome of the single auth prompt.

    ``UNAVAILABLE`` is the caller's fail-open signal (no local security boundary
    exists to honor); every other value is a real gate result.
    """

    SUCCESS = "SUCCESS"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


def authenticate(reason: str | None = None) -> BiometricResult:
    """Show the single auth prompt and return the mapped :class:`BiometricResult`.

    ``reason`` is the localized text the OS shows; the default is used when it is
    empty or ``None``. Blocks until the user responds (or the OS resolves the
    policy); the underlying async completion is bridged synchronously in
    :func:`_evaluate_policy`.
    """
    text = reason if reason else _DEFAULT_REASON
    success, error_code = _evaluate_policy(text)
    result = _result_for(success, error_code)
    _dbg(f"[BiometricGate] authenticate -> {result.value} "
         f"(success={success}, error_code={error_code})")
    return result


def can_authenticate() -> bool:
    """True if the device can evaluate ``deviceOwnerAuthentication`` right now
    (some auth method is configured). Wraps ``LAContext.canEvaluatePolicy``.

    A ``False`` here does not by itself mean "fail open": only an actual
    ``authenticate()`` returning ``UNAVAILABLE`` (``LAErrorPasscodeNotSet``)
    drives the caller's fail-open path. This is a cheap pre-check.
    """
    return _can_evaluate_policy()


def _result_for(success: bool, error_code: int | None) -> BiometricResult:
    """Map a raw ``(success, LAError code)`` result to the enum.

    Order matters: success wins first (so ``(True, None)`` is unambiguous), then
    the "no auth configured" case, then cancels, then everything else - including
    ``authenticationFailed``, any unknown code, and the import-guard's
    ``(False, None)`` - collapses to ``FAILED``.
    """
    if success:
        return BiometricResult.SUCCESS
    if error_code == _LA_ERROR_PASSCODE_NOT_SET:
        return BiometricResult.UNAVAILABLE
    if error_code in _CANCEL_CODES:
        return BiometricResult.CANCELLED
    return BiometricResult.FAILED


# ── Native seams (lazy LocalAuthentication; monkeypatched in tests) ──────────

def _evaluate_policy(reason: str) -> tuple[bool, int | None]:
    """Run ``evaluatePolicy`` synchronously and return ``(success, error_code)``.

    ``evaluatePolicy_localizedReason_reply_`` delivers its result as an async
    completion block on a private background queue, so we block the calling
    thread on a :class:`threading.Event` that the reply sets, then read the
    captured ``(success, error)`` after ``.wait()``. ``error_code`` is the
    ``LAError`` code, or ``None`` on success.

    The ``LocalAuthentication`` binding is imported lazily and guarded: if it is
    absent (off the shipping path, e.g. non-macOS CI) or the native call raises,
    we return ``(False, None)``, which :func:`_result_for` maps to ``FAILED``.
    """
    try:
        import LocalAuthentication  # lazy: keeps import-time side effects at zero
    except Exception as e:  # ImportError off-mac; be defensive about load failures
        _dbg(f"[BiometricGate] LocalAuthentication unavailable: {type(e).__name__}: {e}")
        return (False, None)

    try:
        context = LocalAuthentication.LAContext.alloc().init()
        done = threading.Event()
        captured: dict[str, object] = {"success": False, "error_code": None}

        def _reply(success, error) -> None:
            # Runs on LocalAuthentication's private queue: capture, then signal.
            captured["success"] = bool(success)
            if error is not None:
                try:
                    captured["error_code"] = int(error.code())
                except Exception:
                    captured["error_code"] = None
            done.set()

        context.evaluatePolicy_localizedReason_reply_(
            _POLICY_DEVICE_OWNER_AUTH, reason, _reply
        )
        done.wait()
        return (bool(captured["success"]), captured["error_code"])  # type: ignore[return-value]
    except Exception as e:
        _dbg(f"[BiometricGate] evaluatePolicy raised: {type(e).__name__}: {e}")
        return (False, None)


def _can_evaluate_policy() -> bool:
    """Whether ``deviceOwnerAuthentication`` can be evaluated right now.

    Thin wrapper over ``LAContext.canEvaluatePolicy_error_``; lazy-imports and
    guards the binding exactly like :func:`_evaluate_policy`, returning ``False``
    when it is absent or the call raises.
    """
    try:
        import LocalAuthentication  # lazy
    except Exception as e:
        _dbg(f"[BiometricGate] LocalAuthentication unavailable: {type(e).__name__}: {e}")
        return False
    try:
        context = LocalAuthentication.LAContext.alloc().init()
        ok, _err = context.canEvaluatePolicy_error_(_POLICY_DEVICE_OWNER_AUTH, None)
        return bool(ok)
    except Exception as e:
        _dbg(f"[BiometricGate] canEvaluatePolicy raised: {type(e).__name__}: {e}")
        return False
