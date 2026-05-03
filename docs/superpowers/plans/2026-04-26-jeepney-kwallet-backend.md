# Pure-Python KWallet Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure-Python KWallet keyring backend (using `jeepney`) so packaged AppImage builds can read passwords stored in KDE Wallet without bundling `dbus-python` or `PyGObject`.

**Architecture:** New module `utils/kwallet_jeepney.py` exposes `JeepneyKWalletBackend`, a `keyring.backend.KeyringBackend` subclass that talks to `org.kde.kwalletd6` / `kwalletd5` over the DBus session bus via `jeepney` (already bundled). It registers as a normal keyring backend at priority 5.2 (slightly above keyring's native `kwallet.DBusKeyring` priority 5.1) so it preempts the dbus-python-based variant on systems where both work. `utils/credentials_manager.py` imports the new module so its class is registered as a `KeyringBackend.__subclasses__()` member, and `_available_explicit_backends()` adds it to the manual candidates list.

**Tech Stack:** Python 3.10+, `jeepney` (DBus), `keyring` 25.x, PyInstaller 6.x. No new third-party dependencies.

**Storage layout (compatible with `keyring.backends.kwallet.DBusKeyring`):** wallet = `networkWallet()` (typically `kdewallet`), folder = `service` argument, entry key = `username` argument, value = password string. The user's existing data (folder `toontown_multitool`, 4 account UUID entries) is reachable as-is.

**Validated DBus API (probed live against the user's running kwalletd6):**
- Service `org.kde.kwalletd6`, object `/modules/kwalletd6`, interface `org.kde.KWallet` (kwalletd5 variant uses the same interface at `/modules/kwalletd5`).
- `networkWallet() -> s`
- `open(s wallet, x wId, s appid) -> i` (handle; -1 on failure)
- `isOpen(i handle) -> b`
- `close(i handle, b force, s appid) -> i`
- `hasFolder(i handle, s folder, s appid) -> b`
- `hasEntry(i handle, s folder, s key, s appid) -> b`
- `readPassword(i handle, s folder, s key, s appid) -> s`
- `writePassword(i handle, s folder, s key, s value, s appid) -> i` (0 = ok)
- `removeEntry(i handle, s folder, s key, s appid) -> i` (0 = ok)
- `entryList(i handle, s folder, s appid) -> as`

**File Structure:**
- Create: `utils/kwallet_jeepney.py` — backend implementation (~180 lines).
- Create: `tests/test_kwallet_jeepney.py` — unit + integration tests, skipped when kwalletd is unreachable.
- Modify: `utils/credentials_manager.py` — import the new backend so the class registers; add it to `_available_explicit_backends()` manual candidates; ensure diagnostics list it.
- Modify: `ToonTownMultiTool.spec` — add `utils.kwallet_jeepney` and the relevant `jeepney.wrappers` / `jeepney.io.blocking` submodules to `hiddenimports`.

**Out of scope:**
- Bundling `dbus-python` or `PyGObject` (rejected as portability hazard).
- Migration of passwords between SecretService and KWallet (the user's data is already in KWallet; this backend reads it directly).
- Windows / macOS support (the file is Linux-only and gated by `sys.platform`).

---

### Task 1: Skeleton + DBus daemon detection

**Files:**
- Create: `utils/kwallet_jeepney.py`
- Test: `tests/test_kwallet_jeepney.py`

- [ ] **Step 1: Write the failing test for daemon detection**

Create `tests/test_kwallet_jeepney.py` with:

```python
import sys
import pytest

if sys.platform != "linux":
    pytest.skip("KWallet backend is Linux-only", allow_module_level=True)

from utils.kwallet_jeepney import detect_kwallet_variant


def test_detect_returns_none_when_no_daemon(monkeypatch):
    """When neither kwalletd6 nor kwalletd5 owns its bus name, detection returns None."""
    import utils.kwallet_jeepney as kj
    monkeypatch.setattr(kj, "_session_bus_owns", lambda name: False)
    assert detect_kwallet_variant() is None


def test_detect_prefers_kwalletd6(monkeypatch):
    """If both daemons are present, kwalletd6 wins."""
    import utils.kwallet_jeepney as kj
    owners = {"org.kde.kwalletd6": True, "org.kde.kwalletd5": True}
    monkeypatch.setattr(kj, "_session_bus_owns", owners.get)
    assert detect_kwallet_variant() == ("org.kde.kwalletd6", "/modules/kwalletd6")


def test_detect_falls_back_to_kwalletd5(monkeypatch):
    """If only kwalletd5 is owned, fall back to it."""
    import utils.kwallet_jeepney as kj
    owners = {"org.kde.kwalletd6": False, "org.kde.kwalletd5": True}
    monkeypatch.setattr(kj, "_session_bus_owns", owners.get)
    assert detect_kwallet_variant() == ("org.kde.kwalletd5", "/modules/kwalletd5")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
pytest tests/test_kwallet_jeepney.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'utils.kwallet_jeepney'`.

- [ ] **Step 3: Implement skeleton with `detect_kwallet_variant()`**

Create `utils/kwallet_jeepney.py`:

```python
"""Pure-Python KWallet keyring backend.

Talks to KDE's kwalletd5/kwalletd6 over the session bus via ``jeepney`` so the
AppImage build (which does not bundle ``dbus-python`` or ``PyGObject``) can
still read passwords the user originally stored in KWallet.

Storage layout matches ``keyring.backends.kwallet.DBusKeyring``: folder ==
service, entry key == username, wallet == ``networkWallet()`` (typically
``kdewallet``).
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Optional, Tuple

from keyring.backend import KeyringBackend
from keyring.compat import properties
from keyring.errors import KeyringLocked, PasswordDeleteError, PasswordSetError

_KWALLET_INTERFACE = "org.kde.KWallet"
_VARIANTS: tuple[tuple[str, str], ...] = (
    ("org.kde.kwalletd6", "/modules/kwalletd6"),
    ("org.kde.kwalletd5", "/modules/kwalletd5"),
)
_DBUS_DAEMON = "org.freedesktop.DBus"
_DBUS_PATH = "/org/freedesktop/DBus"
_DBUS_IFACE = "org.freedesktop.DBus"


def _id_from_argv() -> str:
    allowed = (AttributeError, IndexError, TypeError)
    with contextlib.suppress(*allowed):
        return sys.argv[0] or "ToonTownMultiTool"
    return "ToonTownMultiTool"


def _session_bus_owns(name: str) -> bool:
    """Return True if ``name`` currently has an owner on the session bus."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except Exception:
        return False
    addr = DBusAddress(_DBUS_PATH, bus_name=_DBUS_DAEMON, interface=_DBUS_IFACE)
    try:
        with open_dbus_connection(bus="SESSION") as conn:
            msg = new_method_call(addr, "NameHasOwner", "s", (name,))
            reply = conn.send_and_get_reply(msg)
            return bool(reply.body and reply.body[0])
    except Exception:
        return False


def detect_kwallet_variant() -> Optional[Tuple[str, str]]:
    """Return ``(bus_name, object_path)`` for the live KWallet daemon, or None."""
    for bus_name, object_path in _VARIANTS:
        if _session_bus_owns(bus_name):
            return bus_name, object_path
    return None
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
pytest tests/test_kwallet_jeepney.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add utils/kwallet_jeepney.py tests/test_kwallet_jeepney.py
git commit -m "feat(keyring): add jeepney-based KWallet daemon detection"
```

---

### Task 2: KeyringBackend class with priority gating

**Files:**
- Modify: `utils/kwallet_jeepney.py`
- Modify: `tests/test_kwallet_jeepney.py`

- [ ] **Step 1: Add the failing priority test**

Append to `tests/test_kwallet_jeepney.py`:

```python
def test_priority_raises_when_no_daemon(monkeypatch):
    """No live daemon means the backend is not viable."""
    import utils.kwallet_jeepney as kj
    monkeypatch.setattr(kj, "detect_kwallet_variant", lambda: None)
    with pytest.raises(RuntimeError):
        kj.JeepneyKWalletBackend.priority


def test_priority_returns_high_when_kde_and_daemon(monkeypatch):
    """KDE session with a daemon should give priority 5.2."""
    import utils.kwallet_jeepney as kj
    monkeypatch.setattr(kj, "detect_kwallet_variant",
                        lambda: ("org.kde.kwalletd6", "/modules/kwalletd6"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert kj.JeepneyKWalletBackend.priority == 5.2


def test_priority_returns_lower_outside_kde(monkeypatch):
    """Daemon present but not a KDE session: still usable, but lower than native."""
    import utils.kwallet_jeepney as kj
    monkeypatch.setattr(kj, "detect_kwallet_variant",
                        lambda: ("org.kde.kwalletd6", "/modules/kwalletd6"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert kj.JeepneyKWalletBackend.priority == 4.7
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/test_kwallet_jeepney.py::test_priority_raises_when_no_daemon -v
```

Expected: FAIL with `AttributeError: module 'utils.kwallet_jeepney' has no attribute 'JeepneyKWalletBackend'`.

- [ ] **Step 3: Add the class with `priority` classproperty**

Append to `utils/kwallet_jeepney.py`:

```python
class JeepneyKWalletBackend(KeyringBackend):
    """KDE KWallet 5/6 over jeepney (no native dbus-python required)."""

    appid = _id_from_argv() or "ToonTownMultiTool"

    @properties.classproperty
    def priority(cls) -> float:
        if detect_kwallet_variant() is None:
            raise RuntimeError("KWallet daemon not running on the session bus")
        if "KDE" in os.getenv("XDG_CURRENT_DESKTOP", "").split(":"):
            # Slightly higher than keyring's native dbus-python kwallet (5.1)
            # so we preempt it when both are usable. They share storage so
            # there is no data divergence.
            return 5.2
        return 4.7

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cached_address = None
```

- [ ] **Step 4: Run all tests in the file**

```bash
pytest tests/test_kwallet_jeepney.py -v
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add utils/kwallet_jeepney.py tests/test_kwallet_jeepney.py
git commit -m "feat(keyring): JeepneyKWalletBackend class with priority gating"
```

---

### Task 3: get / set / delete password via jeepney

**Files:**
- Modify: `utils/kwallet_jeepney.py`
- Modify: `tests/test_kwallet_jeepney.py`

- [ ] **Step 1: Add an integration test that runs only when kwalletd is up**

Append to `tests/test_kwallet_jeepney.py`:

```python
def test_roundtrip_set_get_delete():
    """End-to-end write -> read -> delete against a live kwalletd."""
    from utils.kwallet_jeepney import JeepneyKWalletBackend, detect_kwallet_variant
    if detect_kwallet_variant() is None:
        pytest.skip("kwalletd not reachable on this session bus")

    backend = JeepneyKWalletBackend()
    service = "toontown_multitool_pytest"
    username = "roundtrip_user"
    secret = "s3cret-value-xyz"

    backend.set_password(service, username, secret)
    try:
        assert backend.get_password(service, username) == secret
    finally:
        backend.delete_password(service, username)

    assert backend.get_password(service, username) is None
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
pytest tests/test_kwallet_jeepney.py::test_roundtrip_set_get_delete -v
```

Expected: FAIL with `AttributeError` (no `set_password` yet) — assuming the user is running this in a KDE Plasma session with kwalletd6 active.

- [ ] **Step 3: Implement the password methods**

First, append the `_KWalletSession` helper class to `utils/kwallet_jeepney.py` (after `JeepneyKWalletBackend`):

```python
class _KWalletSession:
    """Short-lived RAII wrapper around a kwalletd handle."""

    def __init__(self, backend: "JeepneyKWalletBackend"):
        self._backend = backend
        self._conn = None
        self._addr = None
        self._handle: int = -1

    def __enter__(self):
        from jeepney import DBusAddress
        from jeepney.io.blocking import open_dbus_connection

        variant = detect_kwallet_variant()
        if variant is None:
            raise KeyringLocked("KWallet daemon not running")
        bus_name, object_path = variant
        self._addr = DBusAddress(object_path, bus_name=bus_name,
                                 interface=_KWALLET_INTERFACE)
        self._conn = open_dbus_connection(bus="SESSION")

        wallet = self._call("networkWallet", "", ())
        if not wallet:
            self._conn.close()
            raise KeyringLocked("KWallet returned no network wallet")

        handle = self._call("open", "sxs", (wallet, 0, self._backend.appid))
        if not isinstance(handle, int) or handle < 0:
            self._conn.close()
            raise KeyringLocked(f"KWallet open() returned handle={handle!r}")
        self._handle = handle
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._handle >= 0:
                self._call("close", "ibs", (self._handle, False, self._backend.appid))
        except Exception:
            pass
        finally:
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass

    def _call(self, method: str, signature: str, args: tuple):
        from jeepney import new_method_call
        msg = new_method_call(self._addr, method, signature, args)
        reply = self._conn.send_and_get_reply(msg, timeout=5.0)
        # method_return == 2 (jeepney.MessageType.method_return); error == 3
        if reply.header.message_type.value == 3:
            err_name = reply.header.fields.get(4, "<unknown>")
            err_msg = reply.body[0] if reply.body else ""
            raise KeyringLocked(f"KWallet {method} returned error {err_name}: {err_msg}")
        return reply.body[0] if reply.body else None

    @property
    def handle(self) -> int:
        return self._handle
```

Then **replace** the two `NotImplementedError` stubs on `JeepneyKWalletBackend` (added in Task 2) with real implementations, and add `delete_password`. The final class body should look like this — replace from `def get_password` through the second stub:

```python
    def get_password(self, service: str, username: str) -> str | None:
        with _KWalletSession(self) as s:
            if not s._call("hasEntry", "isss",
                           (s.handle, service, username, self.appid)):
                return None
            value = s._call("readPassword", "isss",
                            (s.handle, service, username, self.appid))
            return None if value is None else str(value)

    def set_password(self, service: str, username: str, password: str) -> None:
        with _KWalletSession(self) as s:
            rc = s._call("writePassword", "issss",
                         (s.handle, service, username, password, self.appid))
            if rc != 0:
                raise PasswordSetError(f"KWallet writePassword returned {rc}")

    def delete_password(self, service: str, username: str) -> None:
        with _KWalletSession(self) as s:
            if not s._call("hasEntry", "isss",
                           (s.handle, service, username, self.appid)):
                raise PasswordDeleteError("Password not found")
            rc = s._call("removeEntry", "isss",
                         (s.handle, service, username, self.appid))
            if rc != 0:
                raise PasswordDeleteError(f"KWallet removeEntry returned {rc}")
```

The methods reference `_KWalletSession` which is defined later in the file — that is fine because the reference is resolved at call time, not class-definition time.

- [ ] **Step 4: Run the integration test**

```bash
pytest tests/test_kwallet_jeepney.py::test_roundtrip_set_get_delete -v
```

Expected: PASS (a brief KWallet unlock prompt may appear if the wallet is closed).

- [ ] **Step 5: Run the full test file**

```bash
pytest tests/test_kwallet_jeepney.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add utils/kwallet_jeepney.py tests/test_kwallet_jeepney.py
git commit -m "feat(keyring): jeepney get/set/delete password against kwalletd"
```

---

### Task 4: Register the backend in CredentialsManager

**Files:**
- Modify: `utils/credentials_manager.py`

- [ ] **Step 1: Import the new backend at module load time**

Open `utils/credentials_manager.py`. Find the `import keyring` block near the top of the file (currently around lines 18-19):

```python
import keyring
import keyring.backend
```

Change it to also import the jeepney backend on Linux so its class registers as a `KeyringBackend` subclass:

```python
import keyring
import keyring.backend
import sys as _sys
if _sys.platform == "linux":
    try:
        from utils import kwallet_jeepney as _kwallet_jeepney  # noqa: F401  (registers subclass)
    except Exception:
        _kwallet_jeepney = None
else:
    _kwallet_jeepney = None
```

- [ ] **Step 2: Add the jeepney backend to the explicit candidates list**

Locate `_available_explicit_backends` (currently around lines 340-380). Add a fourth manual-import block after the `kwallet` block (around line 367) and before `backends.extend(manual_candidates)`:

```python
        try:
            if _kwallet_jeepney is not None:
                manual_candidates.append(_kwallet_jeepney.JeepneyKWalletBackend())
        except Exception:
            pass
```

- [ ] **Step 3: Update `_wake_kwallet_if_relevant` to also probe the jeepney backend**

In `_wake_kwallet_if_relevant` (around lines 419-436), change the matching condition so either KWallet implementation triggers the probe. Replace:

```python
            if backend_name != "keyring.backends.kwallet.DBusKeyring":
                continue
```

with:

```python
            if backend_name not in (
                "keyring.backends.kwallet.DBusKeyring",
                "utils.kwallet_jeepney.JeepneyKWalletBackend",
            ):
                continue
```

Leave the rest of the function untouched.

- [ ] **Step 4: Sanity-check the imports**

```bash
python3 -c "
from utils.credentials_manager import CredentialsManager
m = CredentialsManager()
m.run_probe()
backends = m._available_explicit_backends()
print('explicit candidates:')
for b in backends:
    t = type(b)
    print(f'  {t.__module__}.{t.__name__}')
"
```

Expected (on the user's KDE Plasma machine running from source): output includes `utils.kwallet_jeepney.JeepneyKWalletBackend` alongside the dbus-python `keyring.backends.kwallet.DBusKeyring`.

- [ ] **Step 5: Commit**

```bash
git add utils/credentials_manager.py
git commit -m "feat(credentials): register JeepneyKWalletBackend as a chainer child"
```

---

### Task 5: PyInstaller bundling

**Files:**
- Modify: `ToonTownMultiTool.spec`

- [ ] **Step 1: Add hidden imports for the new module and `jeepney.wrappers`**

Open `ToonTownMultiTool.spec`. The existing `hiddenimports=` list already contains `jeepney`, `jeepney.io`, `jeepney.io.blocking`, and `jeepney.bus_messages` on lines 30-33. Insert these two new entries immediately after `'jeepney.bus_messages',`:

```python
        'jeepney.wrappers',
        'utils.kwallet_jeepney',
```

The final `hiddenimports=` list should end with these four `jeepney.*` entries followed by the new `utils.kwallet_jeepney` entry, with no duplicate names anywhere in the list.

- [ ] **Step 2: Verify the spec is syntactically valid**

```bash
python3 -c "
import ast
with open('ToonTownMultiTool.spec') as f:
    ast.parse(f.read())
print('spec OK')
"
```

Expected: `spec OK`.

- [ ] **Step 3: Commit**

```bash
git add ToonTownMultiTool.spec
git commit -m "build(pyinstaller): bundle utils.kwallet_jeepney and jeepney.wrappers"
```

---

### Task 6: Local AppImage smoke test

**Files:** none

- [ ] **Step 1: Build a local AppImage**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
rm -rf build dist AppDir/usr
pyinstaller --noconfirm ToonTownMultiTool.spec
mkdir -p AppDir/usr/bin
cp dist/ToonTownMultiTool AppDir/usr/bin/ToonTownMultiTool
chmod +x AppDir/usr/bin/ToonTownMultiTool
[ -f appimagetool-x86_64.AppImage ] || \
  wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
ARCH=x86_64 ./appimagetool-x86_64.AppImage AppDir TTMultiTool-rc-jeepney-Linux-x86_64.AppImage
```

Expected: AppImage builds without errors.

- [ ] **Step 2: Truncate the credentials debug log so we can inspect a fresh run**

```bash
> ~/.config/toontown_multitool/keyring-debug.log
```

- [ ] **Step 3: Run the new AppImage and try to launch any account**

```bash
./TTMultiTool-rc-jeepney-Linux-x86_64.AppImage
```

In the running app, click **Launch** on any TTR account that previously failed. Close the app afterwards.

- [ ] **Step 4: Inspect the debug log**

```bash
grep -E "Available backends|_get_password|Direct KWallet|Selected keyring backend" ~/.config/toontown_multitool/keyring-debug.log
```

Expected:
- `Available backends:` line MUST contain `utils.kwallet_jeepney.JeepneyKWalletBackend (5.2)`.
- `_get_password(<uuid>): ok=True value=present` (NOT `value=empty`) for the launched account.
- A `Selected keyring backend:` line that includes either `ChainerBackend` (with kwallet_jeepney as a child) or `JeepneyKWalletBackend` directly.

If `value=empty` is still observed, STOP and re-run Phase 1 (root cause investigation) before further changes.

- [ ] **Step 5: Commit nothing (this task is verification only)**

---

### Task 7: CI release-candidate tag

**Files:** none (uses existing release workflow)

- [ ] **Step 1: Push current branch and create a test tag**

```bash
git push origin main
git tag -a v2.0.3-rc4 -m "Test build with jeepney KWallet backend"
git push origin v2.0.3-rc4
```

(If `v2.0.3-rc3` was created by an earlier debug cycle, increment to whatever is unused.)

- [ ] **Step 2: Wait for the workflow run to finish, then download the AppImage from the draft GitHub release**

Check https://github.com/flossbud/ToonTown-MultiTool/actions for the Linux build job; download `TTMultiTool-v2.0.3-rc4-Linux-x86_64.AppImage` from the resulting release.

- [ ] **Step 3: Repeat the smoke test from Task 6 with the CI-built AppImage**

The success criteria are identical: `value=present` for launched accounts, JeepneyKWalletBackend listed in `Available backends:`.

- [ ] **Step 4: If green, delete the rc tag and release**

```bash
gh release delete v2.0.3-rc4 --yes --cleanup-tag
```

(Or via the GitHub UI if `gh` is not authenticated for this repo.)

- [ ] **Step 5: Commit nothing (this task is verification only)**

---

### Task 8: Cut v2.0.3 release

**Files:**
- Modify: `RELEASE_NOTES.md`
- Modify: `main.py` (APP_VERSION), `services/cc_login_service.py` (User-Agent), `services/ttr_login_service.py` (User-Agent)

- [ ] **Step 1: Bump version strings to 2.0.3**

```bash
sed -i 's/APP_VERSION = "2\.0\.2"/APP_VERSION = "2.0.3"/' main.py
sed -i 's|ToontownMultiTool/2\.0\.2|ToontownMultiTool/2.0.3|g' \
    services/cc_login_service.py services/ttr_login_service.py
grep -n "2\.0\.3" main.py services/cc_login_service.py services/ttr_login_service.py
```

Expected: three matches confirming the bump.

- [ ] **Step 2: Rewrite `RELEASE_NOTES.md` for v2.0.3**

Replace the current contents of `RELEASE_NOTES.md` with:

```markdown
## ToonTown MultiTool v2.0.3

Patch release fixing credential storage on KDE Plasma.

---

### Bug Fixes

- Fixed AppImage builds being unable to read passwords stored in KDE Wallet, which caused accounts to fail to launch with no error message after a system reboot.

### Improvements

- Added a portable, pure-Python KWallet backend so packaged builds work on KDE without needing system Python bindings installed.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.3-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.3-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
```

- [ ] **Step 3: Commit and tag**

```bash
git add main.py services/cc_login_service.py services/ttr_login_service.py RELEASE_NOTES.md
git commit -m "chore: release v2.0.3"
git tag -a v2.0.3 -m "v2.0.3"
git push origin main
git push origin v2.0.3
```

The CI release workflow runs on tag push and produces the Windows EXE + Linux AppImage release artifacts.

- [ ] **Step 4: Update the AUR PKGBUILD**

```bash
cd /home/jaret/Projects/aur-toontown-multitool
sed -i 's/pkgver=2\.0\.2/pkgver=2.0.3/' PKGBUILD
sed -i 's/2\.0\.2/2.0.3/g' .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "Update to v2.0.3"
git push aur master
cd /home/jaret/Projects/ToonTownMultiTool-v2
```

Expected: AUR push succeeds; `2.0.3-1` becomes the published version.

- [ ] **Step 5: Verify everything is in sync**

```bash
git -C /home/jaret/Projects/ToonTownMultiTool-v2 log --oneline -5
git -C /home/jaret/Projects/aur-toontown-multitool log --oneline -2
```

The MultiTool repo HEAD should be the v2.0.3 release commit; the AUR repo HEAD should be the matching version bump.
