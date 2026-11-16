"""ToonSession with the services it really builds, and no Multitoon tab.

Runs in a fresh interpreter so "what got imported" means what the session
itself pulled in, not what an earlier test did. Headless: the offscreen Qt
platform, and whatever display connection the input and click-sync backends
can or cannot open (both degrade to "no delivery" without one).
"""

import json
import os
import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent('''
    import json, sys, threading
    from PySide6.QtWidgets import QApplication
    app = QApplication([])

    from services.window_manager import WindowManager
    from utils.settings_manager import SettingsManager
    from utils.keymap_manager import KeymapManager
    from utils.profile_manager import ProfileManager
    from services.toon_session import ToonSession

    settings = SettingsManager()
    window_manager = WindowManager(settings)        # never started: no polling
    session = ToonSession(
        window_manager, settings_manager=settings, keymap_manager=KeymapManager(),
        profile_manager=ProfileManager(), activate=False)

    out = {}
    out["input_service"] = type(session.input_service).__name__
    out["click_sync_service"] = type(session.click_sync_service).__name__
    out["ghosts"] = type(session.ghost_cursor_controller).__name__
    out["customizations"] = type(session.customizations).__name__
    out["getter_is_session"] = (
        session.input_service.get_enabled_toons() is session._slot_enabled)
    out["queue_is_session"] = (
        session.input_service.get_event_queue() is session.key_event_queue)

    # A window list as the poll loop would report it.
    window_manager.ttr_window_ids = ["101", "102"]
    window_manager.window_games = {"101": "ttr", "102": "cc"}
    window_manager.window_ids_updated.emit(["101", "102"])
    out["toons"] = [(t.window_id, t.slot, t.game, t.click_sync_supported)
                    for t in session.toons()]
    out["keysets_known"] = all(
        t.keyset_id in KeymapManager().get_set_ids(t.game) for t in session.toons())
    session.set_enabled("102", False)
    out["enabled_by_slot"] = list(session.input_service.get_enabled_toons())
    session.stop()
    out["stopped"] = list(session.input_service.get_enabled_toons())
    out["suspended"] = session.input_service._routing_suspended
    session.start()
    out["resumed"] = session.input_service._routing_suspended

    session.activate()                               # the real router thread
    out["router_running"] = bool(session.input_service.running)
    out["detection"] = bool(window_manager._detection_enabled)
    session.shutdown()
    out["router_stopped"] = not session.input_service.running
    out["threads_left"] = sorted(
        t.name for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon)

    out["tab_modules"] = sorted(m for m in sys.modules if m.startswith("tabs"))
    print("RESULT " + json.dumps(out))
''')


def test_session_builds_and_runs_the_real_services_without_the_tab(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "TTMT_CONFIG_DIR": str(tmp_path / "config"),
        "HOME": str(tmp_path / "home"),
        "TTMT_NO_VENV_REEXEC": "1",
        "PYTHONPATH": root,
    })
    (tmp_path / "home").mkdir()
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("[ToonSession] core active") == 1
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT "))
    out = json.loads(line[len("RESULT "):])

    assert out["tab_modules"] == []                  # no Multitoon tab, no tab at all
    assert out["input_service"] == "InputService"
    assert out["customizations"] == "ToonCustomizationsManager"
    assert out["getter_is_session"] and out["queue_is_session"]
    if sys.platform in ("linux", "win32", "darwin"):
        assert out["click_sync_service"] == "ClickSyncService"
        assert out["ghosts"] == "GhostCursorController"
        assert out["toons"] == [["101", 0, "ttr", True], ["102", 1, "cc", False]]
    assert out["keysets_known"]
    assert out["enabled_by_slot"] == [True, False, False, False]
    assert out["stopped"] == [False, False, False, False]
    assert out["suspended"] is True and out["resumed"] is False
    assert out["router_running"] and out["detection"]
    assert out["router_stopped"]
    assert out["threads_left"] == []                 # nothing blocks process exit
