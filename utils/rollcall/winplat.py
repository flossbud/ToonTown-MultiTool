"""The Windows calls behind the Roll Call engine (engine_inno.Machine).

ctypes and winreg only: the frozen Roll Call build carries no pywin32. Each
call is small and fails soft (a wrong answer here shows up as a run that
reports a failure, never as an exception in the window).
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

from utils.rollcall import protocol as P
from utils.rollcall.engine_inno import InstallRecord, Machine

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
WAIT_TIMEOUT = 0x102
ERROR_INVALID_PARAMETER = 87
ERROR_SHARING_VIOLATION = 32
ERROR_PIPE_BUSY = 231
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000

_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD)]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                               ctypes.POINTER(wintypes.DWORD)]
_k32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
_k32.GetCurrentProcessId.restype = wintypes.DWORD

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_u32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.GetWindowLongW.restype = ctypes.c_long

UNINSTALL_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class WindowsMachine(Machine):

    # ── Registry ───────────────────────────────────────────────────────────

    def read_install(self, app_id: str, app_name: str) -> InstallRecord | None:
        import winreg
        if not app_id:
            return None
        subkey = f"{UNINSTALL_KEY}\\{app_id}_is1"
        # A per-user install wins when both exist: that is what Setup does
        # for a run that did not choose a mode (installer.iss).
        for root, all_users in ((winreg.HKEY_CURRENT_USER, False),
                                (winreg.HKEY_LOCAL_MACHINE, True)):
            access = winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if all_users else 0)
            try:
                with winreg.OpenKey(root, subkey, 0, access) as key:
                    values = {}
                    for name in ("Inno Setup: App Path", "DisplayVersion", "UninstallString",
                                 "Inno Setup: Selected Tasks", "Inno Setup: Deselected Tasks"):
                        try:
                            values[name] = str(winreg.QueryValueEx(key, name)[0])
                        except OSError:
                            values[name] = ""
            except OSError:
                continue
            directory = values["Inno Setup: App Path"].rstrip("\\")
            if not directory:
                continue
            build = 0
            try:
                with winreg.OpenKey(root, f"Software\\flossbud\\{app_name}", 0, access) as key:
                    build = int(winreg.QueryValueEx(key, "BuildNumber")[0])
            except (OSError, ValueError):
                pass
            uninstaller = values["UninstallString"].strip().strip('"')

            def tasks(text: str) -> tuple:
                return tuple(t.strip().lower() for t in text.split(",") if t.strip())

            return InstallRecord(
                version=values["DisplayVersion"], build=build, directory=directory,
                all_users=all_users, uninstaller=uninstaller,
                selected_tasks=tasks(values["Inno Setup: Selected Tasks"]),
                deselected_tasks=tasks(values["Inno Setup: Deselected Tasks"]))
        return None

    def delete_empty_app_key(self, app_name: str, all_users: bool) -> None:
        import winreg
        root = winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER
        access = winreg.KEY_WOW64_64KEY if all_users else 0
        for subkey in (f"Software\\flossbud\\{app_name}", "Software\\flossbud"):
            try:
                with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | access) as key:
                    sub_count, value_count, _ = winreg.QueryInfoKey(key)
                if sub_count or value_count:
                    return
                winreg.DeleteKeyEx(root, subkey, access, 0)
            except OSError:
                return

    def shortcut_paths(self, app_name: str, all_users: bool) -> list:
        if all_users:
            programs = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                                    "Microsoft", "Windows", "Start Menu", "Programs")
            desktop = os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop")
        else:
            programs = os.path.join(os.environ.get("APPDATA", ""),
                                    "Microsoft", "Windows", "Start Menu", "Programs")
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        group = os.path.join(programs, app_name)
        return [os.path.join(desktop, f"{app_name}.lnk"),
                os.path.join(group, f"{app_name}.lnk"),
                os.path.join(group, f"Uninstall {app_name}.lnk"),
                group]

    # ── Files ──────────────────────────────────────────────────────────────

    def file_free(self, path: str) -> bool:
        if not os.path.exists(path):
            return True
        handle = _k32.CreateFileW(path, GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
        if handle in (None, INVALID_HANDLE_VALUE):
            return ctypes.get_last_error() != ERROR_SHARING_VIOLATION
        _k32.CloseHandle(handle)
        return True

    # ── Processes and windows ──────────────────────────────────────────────

    def is_elevated(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False

    def _all_pids(self) -> list:
        size = 4096
        while True:
            array = (wintypes.DWORD * size)()
            needed = wintypes.DWORD()
            if not _k32.K32EnumProcesses(array, ctypes.sizeof(array), ctypes.byref(needed)):
                return []
            count = needed.value // ctypes.sizeof(wintypes.DWORD)
            if count < size:
                return [array[i] for i in range(count)]
            size *= 2

    def _image(self, pid: int) -> str:
        handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            length = wintypes.DWORD(len(buffer))
            if _k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return buffer.value
            return ""
        finally:
            _k32.CloseHandle(handle)

    def app_pids(self, exe_path: str) -> list:
        if not exe_path:
            return []
        target = _norm(exe_path)
        own = _k32.GetCurrentProcessId()
        found = []
        for pid in self._all_pids():
            if pid in (0, 4, own):
                continue
            image = self._image(pid)
            if image and _norm(image) == target:
                found.append(pid)
        return found

    def pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Gone (87), or there and not ours to open: say alive only then.
            return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
        try:
            code = wintypes.DWORD()
            if not _k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            _k32.CloseHandle(handle)

    def has_visible_window(self, pids) -> bool:
        wanted = set(int(p) for p in pids)
        seen = []

        def callback(hwnd, _lparam):
            pid = wintypes.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in wanted or not _u32.IsWindowVisible(hwnd):
                return True
            if _u32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            rect = wintypes.RECT()
            if _u32.GetWindowRect(hwnd, ctypes.byref(rect)) and \
                    rect.right - rect.left >= 200 and rect.bottom - rect.top >= 120:
                seen.append(hwnd)
                return False
            return True

        _u32.EnumWindows(_WNDENUMPROC(callback), 0)
        return bool(seen)

    def ask_quit(self, server_name: str) -> bool:
        """The app's QLocalServer is a named pipe of the same name."""
        import time
        path = "\\\\.\\pipe\\" + server_name
        handle = None
        for _attempt in range(3):
            handle = _k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, None,
                                      OPEN_EXISTING, 0, None)
            if handle not in (None, INVALID_HANDLE_VALUE):
                break
            if ctypes.get_last_error() != ERROR_PIPE_BUSY:
                return False
            _k32.WaitNamedPipeW(path, 1000)
        else:
            return False
        try:
            data = b"quit\n"
            written = wintypes.DWORD()
            if not _k32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
                return False
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                available = wintypes.DWORD()
                if not _k32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    return False        # closed without an answer
                if available.value:
                    buffer = ctypes.create_string_buffer(64)
                    read = wintypes.DWORD()
                    _k32.ReadFile(handle, buffer, 64, ctypes.byref(read), None)
                    return buffer.raw[:read.value].startswith(b"bye")
                time.sleep(0.05)
            return False
        finally:
            _k32.CloseHandle(handle)

    def restart_manager_close(self, paths) -> bool:
        """What Inno's CloseApplications does: Windows asks each program using
        these files to close (WM_QUERYENDSESSION / WM_ENDSESSION, which Qt
        answers by quitting). Not forced."""
        try:
            rm = ctypes.WinDLL("rstrtmgr")
        except OSError:
            return False
        session = wintypes.DWORD()
        key = ctypes.create_unicode_buffer(64)
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return False
        try:
            files = (wintypes.LPCWSTR * len(paths))(*paths)
            if rm.RmRegisterResources(session, len(paths), files, 0, None, 0, None) != 0:
                return False
            return rm.RmShutdown(session, 0, None) == 0
        finally:
            rm.RmEndSession(session)

    def start(self, exe: str, args, cwd: str = ""):
        # One string, quoted for Inno's parser (utils/rollcall/protocol.py).
        return subprocess.Popen(P.command_line(exe, list(args)), cwd=cwd or None,
                                close_fds=True, creationflags=CREATE_NO_WINDOW)

    def launch_app(self, exe: str, args=()) -> bool:
        if not os.path.isfile(exe):
            return False
        flags = CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
        try:
            subprocess.Popen([exe, *args], cwd=os.path.dirname(exe), close_fds=True,
                             creationflags=flags)
        except OSError as error:
            if getattr(error, "winerror", None) != 5:
                return False
            try:   # this process's job does not allow breaking away
                subprocess.Popen([exe, *args], cwd=os.path.dirname(exe), close_fds=True,
                                 creationflags=CREATE_NEW_PROCESS_GROUP)
            except OSError:
                return False
        return True

    def delete_self_later(self, directory: str) -> None:
        if not directory or not os.path.isdir(directory):
            return
        command = f'cmd.exe /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{directory}"'
        try:
            subprocess.Popen(command, cwd=os.path.dirname(directory), close_fds=True,
                             creationflags=CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            pass
