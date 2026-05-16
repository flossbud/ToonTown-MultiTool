# utils/update_defaults.py
"""First-launch default resolver for update-flow settings.

Called from main.py during startup, after SettingsManager is constructed
but before the main window is shown. No-op on Windows (the installer
always writes check_for_updates_at_startup). On Linux, writes the per-
install-method default only when the key is absent -- never overwrites
a user-set value.
"""
from __future__ import annotations

import utils.install_method as _install_method_mod
from utils.install_method import InstallMethod
from utils.settings_keys import CHECK_FOR_UPDATES_AT_STARTUP


_DEFAULTS_BY_METHOD = {
    InstallMethod.WINDOWS_INSTALLER: None,  # installer writes the key
    InstallMethod.APPIMAGE: True,
    InstallMethod.SOURCE: True,
    InstallMethod.FLATPAK: False,
    InstallMethod.AUR: False,
    InstallMethod.DEB: False,
}


def apply_first_launch_defaults(settings_manager) -> None:
    if CHECK_FOR_UPDATES_AT_STARTUP in settings_manager.settings:
        return
    method = _install_method_mod.detect()
    default = _DEFAULTS_BY_METHOD.get(method)
    if default is None:
        return
    settings_manager.set(CHECK_FOR_UPDATES_AT_STARTUP, default)
