"""Dispatch the update action based on install method.

Each install method has its own handler. Handlers run synchronously
inside the method that called them (most are non-blocking: open browser,
spawn terminal, etc.). The runner is given a reference to its parent
widget so it can show dialogs for the copy-command fallback and error
cases.
"""
from __future__ import annotations

import os
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


_AUR_HELPERS = ["paru", "yay", "pikaur"]
_FLATPAK_APP_ID = "io.github.flossbud.ToonTownMultiTool"


def flatpak_app_id() -> str:
    """Return the Flatpak application ID for this app."""
    return _FLATPAK_APP_ID


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
        cmd = ["flatpak", "update", "-y", _FLATPAK_APP_ID]
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
        cmd = [helper, "-Syu", "--noconfirm", aur_package_name(is_beta=build_flavor.is_beta())]
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
        cmd = ["pkexec", "apt", "install", "-y", path]
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
        # Confirm with the user before launching, then quit and hand off to installer.
        from PySide6.QtWidgets import QMessageBox
        if self._parent is not None:
            box = QMessageBox(self._parent)
            box.setWindowTitle("Install update")
            box.setText(f"Install {info.get('tag_name', 'update')} now?")
            box.setInformativeText(
                "The app will close and the installer will run silently. "
                "The app will restart automatically when the installer finishes."
            )
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Yes)
            if box.exec() != QMessageBox.Yes:
                return
        try:
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES"])
        except (OSError, subprocess.SubprocessError) as e:
            self.failed.emit(f"Failed to launch installer: {e}. Installer saved at {path}")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _download_asset(self, asset: dict) -> Optional[str]:
        import requests
        url = asset.get("browser_download_url")
        name = asset.get("name", "download")
        expected_size = int(asset.get("size", 0))
        if not url:
            return None
        out_dir = tempfile.gettempdir()
        out_path = os.path.join(out_dir, name)
        try:
            with requests.get(url, stream=True, timeout=60) as r:
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
                command=" ".join(cmd),
                note="Couldn't find a terminal emulator. Run this command yourself, then restart the app.",
            )
            return
        self.started_terminal.emit()

    def _show_copy_dialog(self, *, title: str, command: str, note: str) -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox
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
            QApplication.clipboard().setText(command)

    def _open_release_with_toast(self, info: dict, msg: str) -> None:
        url = info.get("html_url")
        if url:
            webbrowser.open(url)
        self.failed.emit(f"{msg} - opening release page.")

    def _restart_app(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])
