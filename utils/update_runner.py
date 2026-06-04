"""Dispatch the update action based on install method.

Each install method has its own handler. Handlers run synchronously
inside the method that called them (most are non-blocking: open browser,
spawn terminal, etc.). The runner is given a reference to its parent
widget so it can show dialogs for the copy-command fallback and error
cases.
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from typing import Optional

from PySide6.QtCore import QObject, Signal

from utils import build_flavor, install_method
from utils.install_method import InstallMethod
from utils.terminal_launcher import run_in_terminal


_log = logging.getLogger(__name__)


_AUR_HELPERS = ["paru", "yay", "pikaur"]
_FLATPAK_APP_ID = "io.github.flossbud.ToonTownMultiTool"


def flatpak_app_id() -> str:
    """Return the Flatpak application ID for this app."""
    return _FLATPAK_APP_ID


def flatpak_install_scope(info_path: str = "/.flatpak-info") -> str:
    """Return the `flatpak install` scope flag ('--system' or '--user') matching
    where THIS Flatpak is deployed, so a reinstall replaces it instead of
    creating a duplicate in the other scope.

    Detected from the deploy path in /.flatpak-info: user installs live under
    ~/.local/share/flatpak, system installs under /var/lib/flatpak. Defaults to
    '--system' (flatpak's own default, and the GitHub-bundle common case) when
    undeterminable.
    """
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(info_path)
        app_path = (cp.get("Instance", "app-path", fallback="")
                    or cp.get("Instance", "original-app-path", fallback=""))
        if "/.local/share/flatpak/" in app_path:
            return "--user"
    except Exception:  # noqa: BLE001
        pass
    return "--system"


def aur_package_name(*, is_beta: bool) -> str:
    """Return the AUR package name for the given channel."""
    return "ttmt-beta" if is_beta else "ttmt"


def pick_asset(assets: list, *, suffix: str) -> Optional[dict]:
    """Return the first asset whose name ends with `suffix` (case-insensitive),
    or None if no match is found.
    """
    for a in assets:
        if a.get("name", "").lower().endswith(suffix.lower()):
            return a
    return None


def find_aur_helper() -> Optional[str]:
    """Return the path of the first AUR helper found on PATH, or None.

    Preference order: paru, yay, pikaur.
    """
    for h in _AUR_HELPERS:
        path = shutil.which(h)
        if path:
            return path
    return None


class UpdateRunner(QObject):
    """Action dispatcher: runs the right update flow for the current install method.

    Signals
    -------
    failed(str)
        Emitted when an error occurs that the UI should surface to the user.
        The string is a human-readable message describing what went wrong.
    started_terminal
        Emitted after a terminal process is successfully spawned so the UI can
        disable interactive buttons until the terminal exits.
    """

    failed = Signal(str)
    started_terminal = Signal()

    def __init__(self, parent_widget=None):
        # Pass None to QObject so PySide6 doesn't type-check parent_widget.
        # Widgets and plain objects (e.g. MagicMock in tests) are both valid
        # callers; we store the reference ourselves for dialog parenting.
        super().__init__(None)
        self._parent = parent_widget

    def run_update(self, release_info: dict) -> None:
        """Dispatch to the appropriate handler for the detected install method."""
        method = install_method.detect()
        handler = {
            InstallMethod.WINDOWS_INSTALLER: self._handle_windows,
            InstallMethod.APPIMAGE: self._handle_appimage,
            InstallMethod.FLATPAK: self._handle_flatpak,
            InstallMethod.AUR: self._handle_aur,
            InstallMethod.DEB: self._handle_deb,
            InstallMethod.SOURCE: self._handle_source,
        }.get(method)
        if handler is None:
            self.failed.emit(f"Unknown install method: {method}")
            return
        handler(release_info)

    # ── Handlers ─────────────────────────────────────────────────────────

    def _handle_appimage(self, info: dict) -> None:
        url = info.get("html_url")
        if not url:
            self.failed.emit("Release URL missing")
            return
        webbrowser.open(url)

    def _handle_source(self, info: dict) -> None:
        cmd = "git pull && pip install -r requirements.txt"
        self._show_copy_dialog(
            title="Update from source",
            command=cmd,
            note="Run this in your terminal, then restart the app.",
        )

    def _handle_flatpak(self, info: dict) -> None:
        # The Flatpak ships as a standalone .flatpak BUNDLE (no Flathub/repo), so
        # the install has no live remote and `flatpak update` silently no-ops.
        # Download the new bundle from the release and reinstall it, the same way
        # the .deb/.exe handlers download-and-install their assets.
        asset = pick_asset(info.get("assets", []), suffix=".flatpak")
        if asset is None:
            self._open_release_with_toast(info, "Couldn't find the Flatpak bundle")
            return
        # Stage where a host-spawned `flatpak install` can read it: the sandbox's
        # /tmp is private to the sandbox, but host_visible_cache_dir is a real
        # host path (under ~/.var/app/<id>/cache, shared via --filesystem=home).
        from utils.host_spawn import in_flatpak, host_visible_cache_dir
        out_dir = host_visible_cache_dir("update") if in_flatpak() else None
        path = self._download_asset(asset, out_dir=out_dir)
        if path is None:
            self.failed.emit("Failed to download the Flatpak bundle")
            return
        # --reinstall forces replacing the existing install with the bundle's new
        # commit even though the ref name (…/master) is unchanged. The explicit
        # scope flag targets the SAME installation this app runs from, so a
        # per-user install isn't shadowed by a duplicate system copy. Runs in a
        # terminal so the polkit prompt for a system install stays visible. Keep
        # the payload raw: run_in_terminal applies the flatpak-spawn --host wrap
        # once around the whole terminal argv (pre-wrapping here would double it).
        cmd = ["flatpak", "install", flatpak_install_scope(), "--reinstall", "-y", path]
        self._spawn_terminal_or_fallback(cmd, info)

    def _handle_aur(self, info: dict) -> None:
        helper = find_aur_helper()
        if helper is None:
            self._show_copy_dialog(
                title="Update from AUR",
                command=f"<your-aur-helper> -Syu {aur_package_name(is_beta=build_flavor.is_beta())}",
                note="No AUR helper found on PATH (tried paru, yay, pikaur).",
            )
            return
        # Intentionally NOT --noconfirm: AUR helpers surface dependency and
        # PKGBUILD-review prompts the user should see for a community-built
        # package. Running interactively in a terminal is fine.
        cmd = [helper, "-Syu", aur_package_name(is_beta=build_flavor.is_beta())]
        self._spawn_terminal_or_fallback(cmd, info)

    def _handle_deb(self, info: dict) -> None:
        asset = pick_asset(info.get("assets", []), suffix=".deb")
        if asset is None:
            self._open_release_with_toast(info, "Couldn't find a .deb asset")
            return
        path = self._download_asset(asset)
        if path is None:
            self.failed.emit("Failed to download the .deb")
            return
        # `dpkg -i` is the canonical local .deb installer (apt install of a
        # path only works on newer apt and isn't portable to all Debian-based
        # distros).
        cmd = ["pkexec", "dpkg", "-i", path]
        self._spawn_terminal_or_fallback(cmd, info)

    def _handle_windows(self, info: dict) -> None:
        asset = pick_asset(info.get("assets", []), suffix=".exe")
        if asset is None:
            self._open_release_with_toast(info, "Couldn't find the installer for your platform")
            return
        path = self._download_asset(asset)
        if path is None:
            self.failed.emit("Failed to download the installer")
            return
        # Never auto-launch without explicit user confirmation; refuse if we
        # have no parent widget to show a dialog from.
        if self._parent is None:
            self.failed.emit("No parent widget to confirm install; aborting.")
            return
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self._parent)
        box.setWindowTitle("Install update")
        box.setText(f"Install {info.get('tag_name', 'update')} now?")
        box.setInformativeText(
            "The app will close while the installer runs, then reopen "
            "automatically when the update finishes."
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() != QMessageBox.Yes:
            return
        try:
            # /RELAUNCH=1 tells the installer to reopen the app after this
            # silent update (we quit it below; the installer's Restart Manager
            # is off, so relaunch is owned by this flag).
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/RELAUNCH=1"])
        except (OSError, subprocess.SubprocessError) as e:
            self.failed.emit(f"Failed to launch installer: {e}. Installer saved at {path}")
            return
        # `QApplication.quit()` posts a quit event but the event loop has to
        # run to process it. Use a singleShot so the installer Popen above
        # actually starts before we tear down.
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _download_asset(self, asset: dict, out_dir: Optional[str] = None) -> Optional[str]:
        import requests
        url = asset.get("browser_download_url")
        raw_name = asset.get("name", "download") or "download"
        name = os.path.basename(raw_name) or "download"
        expected_size = int(asset.get("size", 0))
        if not url:
            return None
        # Default to the system temp dir; callers that need a host-visible path
        # (the Flatpak handler, whose downloaded bundle is installed by a host
        # process) pass an explicit out_dir.
        out_dir = out_dir or tempfile.gettempdir()
        out_path = os.path.join(out_dir, name)
        try:
            # `(connect_timeout, read_timeout)`: 15s to establish, 120s
            # between chunks. The previous single-int timeout only covered
            # connect+headers, leaving a stalled stream to hang indefinitely.
            with requests.get(url, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                with open(out_path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        fh.write(chunk)
        except (requests.RequestException, OSError):
            try:
                os.unlink(out_path)
            except OSError:
                pass
            return None
        # Size sanity check (within 1% or 1 KB, whichever is larger).
        try:
            actual = os.path.getsize(out_path)
            if expected_size > 0 and abs(actual - expected_size) > max(1024, expected_size // 100):
                _log.warning(
                    "Downloaded asset size mismatch: expected %d, got %d (path %s)",
                    expected_size, actual, out_path,
                )
                return None
        except OSError:
            return None
        return out_path

    def _spawn_terminal_or_fallback(self, cmd: list, info: dict) -> None:
        def _on_exit(rc: int):
            if rc != 0:
                self.failed.emit(f"Update command exited with code {rc}")
                return
            self._restart_app()

        ok = run_in_terminal(cmd, _on_exit)
        if not ok:
            # No terminal found; present a copy-command dialog as fallback.
            self._show_copy_dialog(
                title="Update command",
                command=shlex.join(cmd),
                note="Couldn't find a terminal emulator. Run this command yourself, then restart the app.",
            )
            return
        self.started_terminal.emit()

    def _show_copy_dialog(self, *, title: str, command: str, note: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        from utils.clipboard import copy_text
        if self._parent is None:
            return
        box = QMessageBox(self._parent)
        box.setWindowTitle(title)
        box.setText(note)
        box.setDetailedText(command)
        copy_btn = box.addButton("Copy command", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is copy_btn:
            copy_text(command)

    def _open_release_with_toast(self, info: dict, msg: str) -> None:
        url = info.get("html_url")
        if url:
            webbrowser.open(url)
        self.failed.emit(f"{msg} - opening release page.")

    def _restart_app(self) -> None:
        from utils.host_spawn import in_flatpak
        if in_flatpak():
            # The bundle reinstall replaced the deployed app on disk, but THIS
            # sandbox still has the old files mounted, so os.execv would just
            # re-run the old code. Launch a fresh instance on the host (which
            # picks up the new commit) and quit this one.
            from utils.host_spawn import host_popen
            try:
                host_popen(["flatpak", "run", _FLATPAK_APP_ID])
            except Exception as e:  # noqa: BLE001
                _log.warning("flatpak relaunch failed: %s", e)
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
            return
        # `os.execv` replaces the process image immediately, so the Qt event
        # loop never gets a chance to process a `QApplication.quit()` call —
        # exec is what actually terminates this process.
        os.execv(sys.executable, [sys.executable, *sys.argv])
