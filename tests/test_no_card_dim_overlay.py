import importlib
import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def test_card_dim_overlay_module_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("tabs.multitoon._card_dim_overlay")


def test_no_references_remain():
    # git grep only searches tracked files. Exclude THIS test file so its own
    # search-term argument below does not self-match after it is committed.
    import subprocess
    result = subprocess.run(
        ["git", "grep", "-nI", "CardDimOverlay", "--",
         ":(exclude)tests/test_no_card_dim_overlay.py"],
        capture_output=True, text=True,
    )
    # git grep: 0 = matches found, 1 = none. Anything else (e.g. not a repo)
    # would otherwise give a false green, so fail loudly on it.
    assert result.returncode in (0, 1), f"git grep failed: {result.stderr}"
    assert result.stdout.strip() == "", f"stray overlay refs:\n{result.stdout}"
