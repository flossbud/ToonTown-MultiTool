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

if sys.platform != "linux":
    raise ImportError("utils.kwallet_jeepney is Linux-only")

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
    """Return the running executable name, used as the KWallet application ID."""
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


def detect_kwallet_variant() -> tuple[str, str] | None:
    """Return ``(bus_name, object_path)`` for the live KWallet daemon, or None."""
    for bus_name, object_path in _VARIANTS:
        if _session_bus_owns(bus_name):
            return bus_name, object_path
    return None


class JeepneyKWalletBackend(KeyringBackend):
    """KDE KWallet 5/6 over jeepney (no native dbus-python required)."""

    appid = _id_from_argv()

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
        try:
            wallet = self._call("networkWallet", "", ())
            if not wallet:
                raise KeyringLocked("KWallet returned no network wallet")
            handle = self._call("open", "sxs", (wallet, 0, self._backend.appid))
            if not isinstance(handle, int) or handle < 0:
                raise KeyringLocked(f"KWallet open() returned handle={handle!r}")
            self._handle = handle
            return self
        except Exception:
            self._conn.close()
            raise

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
        from jeepney import MessageType, new_method_call
        msg = new_method_call(self._addr, method, signature, args)
        reply = self._conn.send_and_get_reply(msg, timeout=5.0)
        if reply.header.message_type == MessageType.error:
            err_name = reply.header.fields.get(4, "<unknown>")
            err_msg = reply.body[0] if reply.body else ""
            raise KeyringLocked(f"KWallet {method} returned error {err_name}: {err_msg}")
        return reply.body[0] if reply.body else None

    @property
    def handle(self) -> int:
        return self._handle
