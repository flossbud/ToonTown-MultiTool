"""Install-time settings.json merge for the Windows installer.

Invoked via main.py --apply-installer-config from Inno Setup's [Run] section
after files are copied. Single canonical implementation here; the .iss file
calls the just-installed EXE with this flag rather than re-implementing JSON
parsing in Pascal.
"""
import json
import os


def merge_installer_config(
    settings_path: str,
    *,
    check_updates: bool,
    keep_alive: bool,
) -> bool:
    """Merge installer-recorded user choices into settings.json atomically.

    Always writes the 'check_for_updates_at_startup' key (the user explicitly
    answered the wizard question; undefined != explicit false for the future
    auto-update flow).

    Only writes the four Keep-Alive consent keys when keep_alive=True.
    Unchecked means 'leave the in-app consent flow alone' — never strip an
    existing consent marker.

    Preserves all other top-level keys in the existing file.

    Returns True on success. Returns False if the existing file is present
    but not valid JSON; in that case the file is left untouched and the caller
    should log a warning. The app rebuilds defaults on next launch.
    """
    to_merge = {"check_for_updates_at_startup": check_updates}
    if keep_alive:
        to_merge.update({
            "keep_alive_enabled": True,
            "keep_alive_consent_acknowledged": True,
            "keep_alive_consent_source": "installer",
            "keep_alive_consent_version": 1,
        })

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)

    existing: dict = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, dict):
                return False
        except (OSError, json.JSONDecodeError):
            return False

    existing.update(to_merge)

    tmp_path = settings_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, settings_path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False
    return True
