"""
Corporate Clash Launcher Service — handles launching the CorporateClash
process and monitoring its lifecycle (PID, exit code).

Key differences from TTRLauncher:
  - Uses env-var-only credential delivery (TT_PLAYCOOKIE, TT_GAMESERVER,
    LAUNCHER_USER, REALM, SENTRY_ENVIRONMENT) — no CLI args under the
    new launcher protocol. See CCLauncher.launch for the full contract.
  - Different trusted install roots.
  - Different binary name.
"""

from __future__ import annotations

import os
import subprocess
import threading
from PySide6.QtCore import QObject, Signal
from services.cc_login_service import CC_DEFAULT_REALM, CC_ENGINE_SEARCH_PATHS
from services.launcher_env import build_launcher_env
from services.steam_compat_mapping import steam_compat_choice
from services.steam_proton_tools import enumerate_proton_tools
from services.wine_runtimes import WineInstall
from utils.game_registry import GameRegistry
from utils.host_spawn import host_popen

_CUSTOM_APPROVAL_KEY = "cc_engine_dir_approved_custom_dir"


def _approved_custom_engine_dir(settings_manager) -> str | None:
    if settings_manager is None:
        return None
    approved = settings_manager.get(_CUSTOM_APPROVAL_KEY, "")
    return os.path.realpath(approved) if approved else None


def _is_trusted(install: WineInstall, settings_manager) -> bool:
    """Return True when this install is auto-trusted or explicitly approved.

    Discovery-via-known-launcher is the trust signal: classify_path /
    discover_* only build a non-native WineInstall after observing
    structural markers (bottle.yml, compatdata layout, dosdevices/c:, etc.).
    """
    if install.launcher in ("bottles", "lutris", "steam-proton", "wine"):
        return True
    if install.launcher == "native":
        engine_dir = os.path.realpath(os.path.dirname(install.exe_path))
        trusted = {os.path.realpath(p) for p in CC_ENGINE_SEARCH_PATHS}
        if engine_dir in trusted:
            return True
    approved = _approved_custom_engine_dir(settings_manager)
    return bool(
        approved
        and os.path.realpath(os.path.dirname(install.exe_path)) == approved
    )


def _proton_binary_exists(proton_dir: str | None) -> bool:
    if not proton_dir:
        return False
    return os.path.isfile(os.path.join(proton_dir, "proton"))


def _resolve_effective_proton(install: WineInstall, settings_manager) -> str | None:
    """Pick which proton_dir to use for a steam-proton install.

    Cascade (short-circuits on first match):
      1. settings.cc_steam_proton_override (validated)
      2. steam_compat_choice(steam_root, appid) → match enumerate by name
      3. install.metadata["proton_dir"] (today's config_info path)
      4. enumerate_proton_tools()[0] — newest user-installed, or newest
         official if no user-installed Protons exist
      5. None — caller emits launch_failed

    Side effect: step 1 clears a stale override path before falling
    through. Logs exactly one [CCLauncher] resolve_proton: line per call.
    """
    # Step 1: explicit user override.
    override = ""
    if settings_manager is not None:
        override = settings_manager.get("cc_steam_proton_override", "") or ""
    if override:
        if _proton_binary_exists(override):
            print(f"[CCLauncher] resolve_proton: source=override "
                  f"path={override!r}")
            return override
        print(f"[CCLauncher] proton override path no longer exists, "
              f"clearing setting and falling back: {override!r}")
        if settings_manager is not None:
            settings_manager.set("cc_steam_proton_override", "")

    # Step 2: Steam's own CompatToolMapping (per-appid → global).
    steam_root = install.metadata.get("steam_root")
    appid = install.metadata.get("appid")
    if steam_root and appid:
        try:
            name = steam_compat_choice(steam_root, appid)
        except Exception as e:  # pragma: no cover — defensive
            print(f"[CCLauncher] steam_compat_choice raised "
                  f"{type(e).__name__}: {e}; falling back")
            name = None
        if name:
            try:
                tools = enumerate_proton_tools()
            except Exception as e:  # pragma: no cover — defensive
                print(f"[CCLauncher] enumerate_proton_tools raised "
                      f"{type(e).__name__}: {e}; falling back")
                tools = []
            for tool in tools:
                if tool.name == name and _proton_binary_exists(tool.proton_dir):
                    print(f"[CCLauncher] resolve_proton: source=compatmapping "
                          f"name={name!r} path={tool.proton_dir!r}")
                    return tool.proton_dir
            print(f"[CCLauncher] resolve_proton: CompatToolMapping references "
                  f"uninstalled tool {name!r}, falling back")

    # Step 3: config_info (today's behavior).
    cfg_dir = install.metadata.get("proton_dir")
    if _proton_binary_exists(cfg_dir):
        print(f"[CCLauncher] resolve_proton: source=config_info "
              f"path={cfg_dir!r}")
        return cfg_dir

    # Step 4: newest enumerated Proton.
    try:
        tools = enumerate_proton_tools()
    except Exception as e:  # pragma: no cover — defensive
        print(f"[CCLauncher] enumerate_proton_tools raised "
              f"{type(e).__name__}: {e}; falling back to None")
        tools = []
    if tools:
        chosen = tools[0]
        print(f"[CCLauncher] resolve_proton: source=fallback-newest "
              f"path={chosen.proton_dir!r}")
        return chosen.proton_dir

    # Step 5: truly nothing.
    print("[CCLauncher] resolve_proton: source=none — no Steam Proton "
          "installed")
    return None


class CCLauncher(QObject):
    game_launched = Signal(int)     # (pid)
    game_exited = Signal(int)       # (return_code)
    launch_failed = Signal(str)     # (error_message)

    def __init__(self, parent=None, settings_manager=None):
        super().__init__(parent)
        self._game_process = None
        self.settings_manager = settings_manager

    def launch(self, gameserver: str, game_token: str, install,
               username: str = "", realm_slug: str = CC_DEFAULT_REALM):
        """Launch CorporateClash for a discovered install.

        The new (2026) CC launcher protocol passes credentials via env
        vars, not CLI args. CC.exe gates itself behind these env vars
        being present — direct-launch without them gets a "Please launch
        the game from the official launcher!" refusal.

        Env vars (reverse-engineered from new_launcher.exe v1.4.0):
          * TT_PLAYCOOKIE : game token (from /login response's "token")
          * TT_GAMESERVER : hostname from /metadata realms[0].hostname
          * LAUNCHER_USER : account username
          * REALM         : realm slug, "production" today

        Parameters
        ----------
        gameserver : str
            Hostname for TT_GAMESERVER env var. From /metadata.
        game_token : str
            Per-launch game token (TT_PLAYCOOKIE). From /login.
        install : services.wine_runtimes.WineInstall
            Discovered install. Caller is responsible for classification.
        username : str
            Account username for LAUNCHER_USER env var.
        realm_slug : str
            Realm slug for REALM env var. Defaults to "production".
        """
        from services.wine_runtimes import (
            build_launch_command, ensure_bottle_env_allowlist, is_launcher_available,
        )

        # TODO(ttmt-beta → main): gate the [CCLauncher] / [CC] / [wine_runtimes]
        # print() diagnostics behind a single env var (e.g. TTMT_LAUNCH_DEBUG)
        # before the next stable release. The verbose output is invaluable for
        # debugging the new-launcher-protocol path on real user machines, but
        # it spams journalctl --user with token-shaped strings (even masked)
        # in production. Refactor: define _log = print if os.environ.get(...)
        # else lambda *a, **kw: None at module top, replace print() calls.
        # Touches: services/cc_login_service.py, services/cc_launcher.py,
        # services/wine_runtimes.py, tabs/launch_tab.py.

        print(f"[CCLauncher] launch: gameserver='{gameserver}' "
              f"token_len={len(game_token) if game_token else 0} "
              f"user_len={len(username) if username else 0} realm='{realm_slug}' "
              f"install.launcher={install.launcher!r} "
              f"install.exe_path={install.exe_path!r} "
              f"install.prefix_path={install.prefix_path!r}")

        if not os.path.isfile(install.exe_path):
            print(f"[CCLauncher] launch: exe_path NOT a file; aborting")
            self.launch_failed.emit(
                f"CorporateClash not found at {install.exe_path}"
            )
            return

        if not _is_trusted(install, self.settings_manager):
            print(f"[CCLauncher] launch: install NOT trusted; aborting")
            self.launch_failed.emit(
                "CorporateClash path is not in the trusted install list. "
                "Re-select it in Settings to approve a custom install."
            )
            return

        if not is_launcher_available(install.launcher):
            print(f"[CCLauncher] launch: launcher '{install.launcher}' NOT available; aborting")
            self.launch_failed.emit(
                self._availability_error_message(install.launcher)
            )
            return

        # No CLI args under the new launcher protocol — everything is env.
        args: list[str] = []
        extra_env: dict[str, str] = {}
        if game_token:
            extra_env["TT_PLAYCOOKIE"] = game_token
        if gameserver:
            extra_env["TT_GAMESERVER"] = gameserver
        if username:
            extra_env["LAUNCHER_USER"] = username
        if realm_slug:
            extra_env["REALM"] = realm_slug
        # Sentry env tag the launcher sets unconditionally. CC.exe likely
        # only inspects this when sentry is enabled, but the official
        # launcher always sets it, so we mirror that to stay
        # bit-identical to the official flow.
        extra_env["SENTRY_ENVIRONMENT"] = "corporateclash"

        # Bottles strips any env vars not in the bottle's allowlist when
        # Limit_System_Environment is on. Extend the allowlist with the
        # keys we just decided to pass — without this, none of the
        # TT_*/LAUNCHER_USER/REALM vars reach CC.exe and the game
        # silently exits rc=0 with no log file written.
        if install.launcher == "bottles":
            ensure_bottle_env_allowlist(
                install.prefix_path,
                list(extra_env.keys()),
            )

        try:
            cmd, env_overrides = build_launch_command(install, args, extra_env)
        except ValueError as e:
            print(f"[CCLauncher] launch: build_launch_command ValueError {e}")
            self.launch_failed.emit(f"Cannot build launch command: {e}")
            return

        spawn_env = build_launcher_env(env_overrides)
        cwd = install.prefix_path or os.path.dirname(install.exe_path)
        # Keys whose values must never appear in plain text in the log.
        # TT_PLAYCOOKIE is the game-session token (auth secret). LAUNCHER_USER
        # is the account username — PII that would otherwise leak when a
        # user pastes terminal output into a public issue tracker.
        sensitive = {"TT_PLAYCOOKIE", "LAUNCHER_USER"}
        safe_env_keys = sorted(k for k in env_overrides if k not in sensitive)
        masked_keys = sorted(k for k in env_overrides if k in sensitive)
        print(f"[CCLauncher] launch: cmd={cmd}")
        print(f"[CCLauncher] launch: cwd={cwd}")
        print(f"[CCLauncher] launch: env_overrides plain={safe_env_keys} "
              f"masked={masked_keys}")

        def _run():
            import sys
            import tempfile
            # Capture BOTH stdout and stderr to temp files. DXVK 'info:'
            # lines and CC's own progress messages go to stdout; bottles
            # / wine / fsync messages go to stderr. We need both to
            # diagnose silent exits. Use mkstemp (atomic create+name) so
            # there's no TOCTOU between picking a name and opening it.
            stdout_fd, stdout_path = tempfile.mkstemp(prefix="ttmt-cc-stdout-", suffix=".log")
            stderr_fd, stderr_path = tempfile.mkstemp(prefix="ttmt-cc-stderr-", suffix=".log")
            stdout_fh = os.fdopen(stdout_fd, "w+b")
            stderr_fh = os.fdopen(stderr_fd, "w+b")
            retcode = None
            try:
                kwargs = {}
                if sys.platform == "win32" and install.launcher == "native":
                    kwargs["creationflags"] = (
                        subprocess.DETACHED_PROCESS
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_BREAKAWAY_FROM_JOB
                    )

                def _spawn():
                    return host_popen(
                        cmd,
                        cwd=cwd,
                        env=spawn_env,
                        stdout=stdout_fh,
                        stderr=stderr_fh,
                        **kwargs,
                    )

                print(f"[CCLauncher] _run: spawning… (stdout {stdout_path}, stderr {stderr_path})")
                try:
                    self._game_process = _spawn()
                except OSError as e:
                    if sys.platform != "win32" or getattr(e, "winerror", None) != 5:
                        raise
                    kwargs["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
                    self._game_process = _spawn()
                pid = self._game_process.pid
                print(f"[CCLauncher] _run: spawned pid={pid}")
                GameRegistry.instance().register(pid, "cc")
                self.game_launched.emit(pid)

                retcode = self._game_process.wait()
                print(f"[CCLauncher] _run: child exited rc={retcode}")

                def _dump(label, fh, path):
                    try:
                        fh.flush()
                        fh.seek(0)
                        content = fh.read().decode("utf-8", "replace").strip()
                    except Exception as e:
                        content = f"<failed to read {label} capture: {e}>"
                    if not content:
                        print(f"[CCLauncher] _run: {label} from child (rc={retcode}): <empty>")
                        return
                    snippet = content
                    if len(snippet) > 4000:
                        snippet = snippet[:4000] + f"\n…(+{len(content)-4000} more bytes; full at {path})"
                    print(f"[CCLauncher] _run: {label} from child (rc={retcode}):\n{snippet}\n[CCLauncher] _run: --- end {label} ---")

                # Dump both streams regardless of exit code so we can
                # diagnose silent exits where rc=0 but nothing happens.
                _dump("stdout", stdout_fh, stdout_path)
                _dump("stderr", stderr_fh, stderr_path)
                GameRegistry.instance().unregister(pid)
                self._game_process = None
                self.game_exited.emit(retcode)

            except Exception as e:
                print(f"[CCLauncher] _run: error {type(e).__name__}: {e}")
                self.launch_failed.emit(f"Launch error: {e}")
            finally:
                # Always close both fds. Without this each successful
                # launch leaks two file descriptors on the parent.
                for fh in (stdout_fh, stderr_fh):
                    try:
                        fh.close()
                    except Exception:
                        pass
                # Unlink capture files on clean exit. Preserve them on
                # rc != 0 or on exception so the user can grep them
                # post-hoc. Without this every launch accumulates two
                # files in /tmp indefinitely.
                if retcode == 0:
                    for path in (stdout_path, stderr_path):
                        try:
                            os.unlink(path)
                        except OSError:
                            pass

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _availability_error_message(launcher: str) -> str:
        messages = {
            "bottles": (
                "Detected Corporate Clash inside Bottles, but bottles-cli is "
                "not available on this system. Install Bottles or pick a "
                "different install in Settings."
            ),
            "lutris": (
                "Detected Corporate Clash in a Lutris-managed prefix, but the "
                "wine binary is not available. Install wine or pick a "
                "different install in Settings."
            ),
            "steam-proton": (
                "Detected Corporate Clash in a Steam Proton prefix, but Steam "
                "is not available. Launch Steam or pick a different install."
            ),
            "wine": (
                "Detected Corporate Clash in a Wine prefix, but the wine "
                "binary is not available. Install wine or pick a different "
                "install in Settings."
            ),
        }
        return messages.get(
            launcher,
            f"Required runtime for launcher '{launcher}' is not available.",
        )

    def kill(self):
        """Terminate the game process if running."""
        if self._game_process and self._game_process.poll() is None:
            try:
                self._game_process.kill()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._game_process is not None and self._game_process.poll() is None
