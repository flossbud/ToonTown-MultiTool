import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(extra_env):
    env = dict(os.environ)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "main.py", "--self-check-keyring"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_self_check_keyring_fails_without_secret_service():
    """With keyring forced to the non-functional 'fail' backend,
    --self-check-keyring must exit non-zero rather than silently passing."""
    result = _run({"PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"})
    assert result.returncode != 0, (
        f"--self-check-keyring should fail on the 'fail' backend\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _secret_service_available():
    try:
        import keyring
        from keyring.backends import SecretService

        return isinstance(keyring.get_keyring(), SecretService.Keyring)
    except Exception:
        return False


@pytest.mark.skipif(
    not _secret_service_available(),
    reason="no functional Secret Service backend on this host (CI test-keyring job covers it)",
)
def test_self_check_keyring_roundtrip_passes():
    """On a host with a working Secret Service, the store/retrieve/delete
    roundtrip must succeed and the process must exit 0."""
    result = _run({})
    assert result.returncode == 0, (
        f"--self-check-keyring failed (exit {result.returncode})\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
