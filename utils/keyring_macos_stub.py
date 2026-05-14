"""Pre-seed sys.modules to dodge a shiboken6 + keyring fatal-error race.

The keyring package's entry-points discovery loads every declared backend,
including `keyring.backends.macOS`. On non-Darwin hosts that submodule's
`__init__.py` does ``try: from . import api except Exception: pass``, which
silently absorbs the inner `api.py` import failure when it hits the
CoreFoundation/Security symbol loads via ctypes. The trouble is that
`api.py` defines ``class error`` BEFORE the ctypes call that explodes — so
Python:

  1. Creates ``sys.modules["keyring.backends.macOS.api"]`` (partial)
  2. Executes top-of-module → defines ``class error`` (its ``__module__``
     attribute is set to ``"keyring.backends.macOS.api"``)
  3. Hits the ctypes load, raises AttributeError
  4. Removes ``"keyring.backends.macOS.api"`` from sys.modules

…leaving a class object floating in memory whose ``__module__`` points at a
module name no longer in ``sys.modules``. Later, shiboken6's signature
mapping walks every class it knows about and indexes by ``__module__``; the
first time it has to format a signature error, the genexpr at
``shibokensupport/signature/mapping.py:190`` does a dict lookup on that
missing name, KeyErrors, and shiboken's C code calls ``Py_FatalError`` from
inside ``seterror_argument``. The whole interpreter aborts (SIGABRT).

We reproduced this on Fedora 44 KDE Wayland at roughly 60% per launch from
source. Pre-seeding ``sys.modules`` with a stub for the missing name makes
the keyring backend's ``from . import api`` short-circuit on the stub (so
the real ``api.py`` never runs and the dangling-class state never exists)
and guarantees shiboken's lookup succeeds for the lifetime of the process.

This file must be importable without pulling in keyring, PySide6, or any
Qt / ctypes machinery, because main.py calls ``install_stub()`` before any
of those modules are imported. Keep the import list to stdlib only.
"""

from __future__ import annotations

import sys
import types

_STUB_MODULE_NAME = "keyring.backends.macOS.api"


def install_stub() -> bool:
    """Install the stub module if needed.

    Returns True if a stub was installed (or was already present), False if
    we skipped because we're on macOS where the real module loads fine.
    """
    if sys.platform == "darwin":
        return False
    if _STUB_MODULE_NAME in sys.modules:
        return True
    stub = types.ModuleType(_STUB_MODULE_NAME)
    sys.modules[_STUB_MODULE_NAME] = stub
    return True
