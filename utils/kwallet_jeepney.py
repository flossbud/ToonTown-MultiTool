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
