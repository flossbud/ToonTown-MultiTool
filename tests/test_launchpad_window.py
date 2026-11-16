"""The launchpad window (the default; TTMT_NEXT_UI=0 selects the classic
window): what it builds, what it does not,
and how its header, sheets and services are wired.

These build the real window offscreen. They are construction checks; how it
looks and behaves on a desktop is for a live run.
"""

import os

# Before any `import main`: without it main.py re-execs into ./venv on import.
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

from utils.widgets.launchpad.header import (
    SHEET_ACCOUNTS, SHEET_KEYSETS, SHEET_SETTINGS,
)


def _dispose(window, qapp):
    """Shut the window down and really delete it. A window left alive keeps
    its app-wide event filters (window chrome), and every later test pays
    for each one on every event."""
    from PySide6.QtCore import QCoreApplication, QEvent
    window.shutdown()
    window.close()
    # Let zero-delay callbacks queued by its widgets (a combo styling its
    # popup on first show, say) run while those widgets still exist.
    qapp.processEvents()
    qapp.processEvents()
    # A launcher card reacts to losing focus by restyling its children; mid
    # deletion they are already gone. Take the focus away first.
    focused = qapp.focusWidget()
    if focused is not None:
        focused.clearFocus()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _settle(qapp, seconds=0.6):
    """Let the sheet's slide animation run out."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


@pytest.fixture
def isolated(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TTMT_SELF_CHECK", "1")      # no update thread, no network
    # The suite pins the previous launcher as the default; the launchpad
    # mounts Grandstand regardless, and sets this itself when it is not.
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr("utils.update_checker.UpdateChecker.check_async",
                        lambda self, *, manual: True)
    # Closing the window must not quit the test run's QApplication.
    quits = []
    monkeypatch.setattr("utils.launchpad_window._quit_app", lambda: quits.append(1))
    return quits


@pytest.fixture
def window(isolated, monkeypatch, qapp):
    constructed = []

    def record(cls_path):
        module_name, _, cls_name = cls_path.rpartition(".")
        module = __import__(module_name, fromlist=[cls_name])
        cls = getattr(module, cls_name)
        original = cls.__init__

        def tracking_init(self, *args, **kwargs):
            constructed.append(cls_name)
            original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", tracking_init)

    for path in ("tabs.multitoon._tab.MultitoonTab", "tabs.settings_tab.SettingsTab",
                 "tabs.credits_tab.CreditsTab", "tabs.launch_tab.LaunchTab",
                 "services.toon_session.ToonSession"):
        record(path)

    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    win.constructed = constructed
    win.resize(880, 860)
    win.show()
    qapp.processEvents()
    yield win
    _dispose(win, qapp)


# ── The switch ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    ("1", True), (" 1 ", True), ("", True), ("true", True), ("2", True),
    ("0", False), (" 0 ", False),
])
def test_only_an_explicit_zero_selects_the_classic_window(value, expected):
    from utils.launchpad_window import next_ui_enabled
    assert next_ui_enabled({"TTMT_NEXT_UI": value}) is expected
    assert next_ui_enabled({}) is True


def test_main_picks_the_launchpad_by_default(monkeypatch):
    import main
    from utils.launchpad_window import LaunchpadWindow
    monkeypatch.delenv("TTMT_NEXT_UI", raising=False)
    assert main._main_window_class() is LaunchpadWindow
    monkeypatch.setenv("TTMT_NEXT_UI", "1")
    assert main._main_window_class() is LaunchpadWindow


def test_main_picks_the_classic_window_with_the_escape_hatch(monkeypatch, capsys):
    import main
    monkeypatch.setenv("TTMT_NEXT_UI", "0")
    assert main._main_window_class() is main.MultiToonTool
    assert "[NextUI] classic window (TTMT_NEXT_UI=0)" in capsys.readouterr().out


def test_the_classic_window_is_what_it_was(isolated, monkeypatch, qapp):
    """TTMT_NEXT_UI=0: the same class, with its Multitoon tab and nav band."""
    import main
    monkeypatch.setenv("TTMT_NEXT_UI", "0")
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    monkeypatch.setattr(main, "_quit_app_after_main_window_close", lambda: None)
    win = main._main_window_class()()
    try:
        assert type(win) is main.MultiToonTool
        assert type(win.multitoon_tab).__name__ == "MultitoonTab"
        assert hasattr(win, "nav_band") and not hasattr(win, "session")
    finally:
        win.shutdown()
        win.close()


# ── What it builds ─────────────────────────────────────────────────────────

def test_no_multitoon_tab_is_constructed(window):
    assert "MultitoonTab" not in window.constructed
    assert "SettingsTab" not in window.constructed
    assert "CreditsTab" not in window.constructed
    assert window.constructed.count("ToonSession") == 1
    assert window.constructed.count("LaunchTab") == 1
    assert not hasattr(window, "multitoon_tab")


def test_stamps_are_printed_once(isolated, capsys, qapp):
    from utils.launchpad_window import STAMP, LaunchpadWindow
    win = LaunchpadWindow()
    try:
        out = capsys.readouterr().out
        assert STAMP == "[NextUI] launchpad window + float strips (default; TTMT_NEXT_UI=0 selects the classic window)"
        assert out.count(STAMP) == 1
        assert out.count("[ToonSession] core active") == 1
        # The strips print theirs once per process; see the self-check test.
        assert out.count("[Strips] attach=") <= 1
    finally:
        _dispose(win, qapp)


def test_a_real_start_prints_each_stamp_exactly_once(tmp_path):
    """The running-code proof a live check begins with: `main.py --self-check`
    in a fresh interpreter, with the flag unset (the default)."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "home").mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               TTMT_NO_VENV_REEXEC="1", TTMT_CONFIG_DIR=str(tmp_path / "config"),
               HOME=str(tmp_path / "home"))
    env.pop("TTMT_GRANDSTAND", None)
    env.pop("TTMT_NEXT_UI", None)
    proc = subprocess.run([sys.executable, "main.py", "--self-check"], cwd=root,
                          env=env, capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-2000:]
    assert "self-check OK" in out
    assert out.count("[NextUI] launchpad window + float strips (default; TTMT_NEXT_UI=0 selects the classic window)") == 1
    assert out.count("[ToonSession] core active") == 1
    assert out.count("[Strips] attach=") == 1
    assert "Traceback" not in out


def test_the_launcher_is_the_only_page(window):
    from tabs.launch_tab import LaunchTab
    layout = window.container.layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert widgets == [window.header, window.update_banner,
                       window.admin_notice_banner, window.launch_tab]
    assert isinstance(window.launch_tab, LaunchTab)
    assert window.launch_tab.isVisible()
    assert getattr(window.launch_tab, "grandstand", None) is not None
    assert not hasattr(window, "nav_band") and not hasattr(window, "stack")


def test_the_previous_launcher_cannot_be_mounted_in_the_launchpad(
        isolated, monkeypatch, capsys, qapp):
    from utils.launchpad_window import LaunchpadWindow
    monkeypatch.setenv("TTMT_GRANDSTAND", "0")
    win = LaunchpadWindow()
    try:
        assert getattr(win.launch_tab, "grandstand", None) is not None
        assert "TTMT_GRANDSTAND=0 is ignored" in capsys.readouterr().out
    finally:
        _dispose(win, qapp)


def test_the_launcher_fills_the_window_under_the_header(window):
    header = window.header.geometry()
    launcher = window.launch_tab.geometry()
    assert header.height() == 112
    assert launcher.top() == header.bottom() + 1        # no nav band between
    assert launcher.height() >= 700


def test_session_and_launcher_share_what_they_must(window):
    session = window.session
    assert session._window_manager is window.window_manager
    assert session._toon_capture_sink == window.launch_tab.capture_toon
    assert window.launch_tab._customizations is session.customizations
    assert session.input_service.get_chat_block_list() == {"Return", "Escape"} \
        or isinstance(session.input_service.get_chat_block_list(), (set, frozenset))
    assert callable(session.input_service.get_chat_open_chords)


def test_main_can_drive_it_like_the_classic_window(window):
    """main.py calls these on whichever window it built."""
    assert window._maybe_enter_float_mode_at_startup() is False
    assert window._maybe_notify_float_startup_recovered() is None
    assert window.settings_manager is not None
    window.log("[Test] line")
    assert callable(window.shutdown)


# ── Header ─────────────────────────────────────────────────────────────────

def test_session_status_follows_the_toons(window, qapp):
    wm = window.window_manager
    assert window.header.status.text() == ""
    assert not window.header.status.isVisible()
    wm.ttr_window_ids = ["101", "102"]
    wm.window_games = {"101": "ttr", "102": "ttr"}
    window.session._on_window_ids(["101", "102"])
    window.session.start()
    assert window.header.status.text() == "2 toons"
    assert window.header.status.isVisible()
    wm.ttr_window_ids = ["101"]
    window.session._on_window_ids(["101"])
    assert window.header.status.text() == "1 toon"
    window.session.stop()                       # the toon is still up, broadcast stopped
    assert window.header.status.text() == "1 toon \u00b7 stopped"
    window.session.start()
    assert window.header.status.text() == "1 toon"
    wm.ttr_window_ids = []
    window.session._on_window_ids([])
    assert window.header.status.text() == ""


def test_hints_toggle_persists_and_blocks_tooltips(window):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QPushButton
    assert window._hints_enabled is True
    window.header.hint_btn.click()
    assert window._hints_enabled is False
    assert window.settings_manager.get("hints_enabled") is False
    tip = QEvent(QEvent.ToolTip)
    plain = QPushButton()
    assert window.eventFilter(plain, tip) is True                   # blocked
    assert window.eventFilter(window.header.hint_btn, tip) is False  # its own shows
    window.header.hint_btn.click()
    assert window.eventFilter(plain, tip) is False


# ── Sheets ─────────────────────────────────────────────────────────────────

def test_a_header_button_opens_its_sheet_and_lights_up(window, qapp):
    assert window.open_sheet_name() is None
    window.header.buttons.buttons[SHEET_SETTINGS].click()
    assert window.open_sheet_name() == SHEET_SETTINGS
    assert window.header.open_sheet() == SHEET_SETTINGS
    assert window.sheet_host.is_open()
    assert window.sheet_host.isVisible()


def test_pressing_the_lit_button_closes_its_sheet(window, qapp):
    button = window.header.buttons.buttons[SHEET_ACCOUNTS]
    button.click()
    button.click()
    assert window.open_sheet_name() is None
    assert window.header.open_sheet() is None
    assert not window.sheet_host.is_open()


def test_pressing_another_button_swaps_sheets(window, qapp):
    window.header.buttons.buttons[SHEET_ACCOUNTS].click()
    window.header.buttons.buttons[SHEET_SETTINGS].click()
    assert window.open_sheet_name() == SHEET_SETTINGS
    assert window.header.open_sheet() == SHEET_SETTINGS
    assert window.sheet_host.is_open()


def test_closing_from_the_sheet_itself_unlights_the_button(window, qapp):
    window.header.buttons.buttons[SHEET_SETTINGS].click()
    window.sheet_host.close()                   # scrim click, Esc, close button
    assert window.header.open_sheet() is None
    assert window.open_sheet_name() is None


def test_the_sheet_sits_under_the_header_over_the_launcher(window, qapp):
    window.open_sheet(SHEET_SETTINGS)
    _settle(qapp)
    host = window.sheet_host.geometry()
    assert host.top() >= window.header.geometry().bottom()
    assert window.sheet_host.parent() is window.container
    panel = window.sheet_host.panel
    assert panel.width() == 664
    assert panel.mapTo(window.container, panel.rect().topRight()).x() >= \
        window.container.width() - 3


def test_keysets_button_opens_the_real_keysets_sheet(window, qapp):
    from utils.widgets.launchpad.keysets_sheet import KeysetsSheet
    window.header.buttons.buttons[SHEET_KEYSETS].click()
    sheet = window.sheet_host.current_content()
    assert isinstance(sheet, KeysetsSheet)
    assert sheet._km is window.keymap_manager
    assert window.sheet_host.panel.header.title_label.text() == KeysetsSheet.TITLE
    assert window.header.open_sheet() == SHEET_KEYSETS


def test_keysets_sheet_opens_on_the_game_the_launcher_shows(window, qapp):
    window.launch_tab.grandstand._party.set_active_game("cc")
    assert window._launcher_game() == "cc"
    window.open_sheet(SHEET_KEYSETS)
    assert window.sheet_host.current_content()._game == "cc"
    window.open_sheet(None)
    window.launch_tab.grandstand._party.set_active_game("ttr")
    window.open_sheet(SHEET_KEYSETS)
    assert window.sheet_host.current_content()._game == "ttr"


def test_a_registered_sheet_replaces_the_placeholder(window, qapp):
    from PySide6.QtWidgets import QWidget
    window.open_sheet(SHEET_ACCOUNTS)
    placeholder = window.sheet_host.current_content()
    real = QWidget()
    real.TITLE, real.SUB, real.IDENTITY = "Accounts", "Sub line", "#0077ff"
    window.register_sheet(SHEET_ACCOUNTS, real)
    assert window.sheet_host.current_content() is real      # swapped while open
    assert window.sheet_host.current_content() is not placeholder
    assert window.header.open_sheet() == SHEET_ACCOUNTS
    with pytest.raises(ValueError):
        window.register_sheet("nope", QWidget())


# ── Wiring ─────────────────────────────────────────────────────────────────

def test_hotkey_actions_reach_the_session(window, monkeypatch):
    from utils.hotkey_actions import ACTIONS
    assert set(window._hotkey_dispatch) == {a.id for a in ACTIONS}
    calls = []
    monkeypatch.setattr(window.session, "refresh", lambda: calls.append("refresh"))
    window._hotkey_dispatch = dict(window._hotkey_dispatch, **{
        "app.refresh": window.session.refresh})
    assert window.session.is_running()
    window._on_hotkey_action("service.toggle")
    assert not window.session.is_running()
    window._on_hotkey_action("service.toggle")
    assert window.session.is_running()
    window._on_hotkey_action("app.refresh")
    assert calls == ["refresh"]
    window._on_hotkey_action("no.such.action")          # dropped, no raise
    window._on_hotkey_action("overlay.toggle_cards")    # no float mode: no-op


def test_hotkey_actions_are_ignored_while_a_chord_is_being_recorded(window, monkeypatch):
    from utils import chord_capture_state
    monkeypatch.setattr(chord_capture_state, "is_active", lambda: True)
    window._on_hotkey_action("service.toggle")
    assert window.session.is_running()


def test_profile_hotkey_loads_through_the_session(window, monkeypatch):
    loaded = []
    monkeypatch.setattr(window.session, "load_profile", loaded.append)
    window._hotkey_dispatch["profile.load_3"]()
    assert loaded == [2]
    assert window.settings_manager.get("active_profile") == 2


def test_a_look_saved_in_the_launcher_reaches_the_session(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window.session, "customization_changed",
                        lambda game, name: seen.append((game, name)))
    window.launch_tab.look_saved.emit("ttr", "Flossbud")
    assert seen == [("ttr", "Flossbud")]


def test_chat_state_is_passed_on_once_per_change(window):
    seen = []
    window.chat_active_changed.connect(seen.append)
    service = window.session.input_service
    service.chat_state_changed.emit(True)
    service.chat_state_changed.emit(True)
    service.chat_state_changed.emit(False)
    assert seen == [True, False]
    assert window.chat_active() is False


def test_the_elevation_prompt_opens_for_blocked_input(window, monkeypatch):
    shown = []

    class FakeDialog:
        def __init__(self, affected_toons, parent=None):
            shown.append(affected_toons)
            self.restart_as_admin = self.dont_ask_again = self

        def connect(self, _slot):
            pass

        def exec(self):
            pass

    monkeypatch.setattr("utils.widgets.uipi_elevation_dialog.UipiElevationDialog",
                        FakeDialog)
    details = {"targets": [{"toon_index": 1}, {"toon_index": 2}]}
    window.session.input_service.uipi_blocked_movement_detected.emit(details)
    assert shown == [["Toon 2", "Toon 3"]]
    from utils.settings_keys import UIPI_ELEVATION_PROMPT_DISMISSED
    window.settings_manager.set(UIPI_ELEVATION_PROMPT_DISMISSED, True)
    window.session.input_service.uipi_blocked_movement_detected.emit(details)
    assert len(shown) == 1                          # dismissed for good


def test_a_theme_change_restyles_header_and_sheets(window, qapp):
    window.open_sheet(SHEET_SETTINGS)
    window.settings_manager.set("theme", "light")
    assert window._is_dark() is False
    assert window.header._dark is False
    assert window.sheet_host._is_dark is False
    window.settings_manager.set("theme", "dark")
    assert window.header._dark is True
    assert window.sheet_host._is_dark is True


def test_the_logging_setting_reaches_the_router_live(window):
    window.settings_manager.set("show_debug_tab", True)
    assert window.debug_tab.logging_enabled is True
    assert window.session.input_service.logging_enabled is True
    window.settings_manager.set("show_debug_tab", False)
    assert window.session.input_service.logging_enabled is False


def test_keep_alive_sleep_warning_shows_once(window, monkeypatch):
    from types import SimpleNamespace
    shown = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.exec",
                        lambda self: shown.append(self.windowTitle()))
    held = SimpleNamespace(sleep_blocked=True, method="x")
    missing = SimpleNamespace(sleep_blocked=False, method="x")
    window.session.keep_alive_inhibit_status.emit(held)
    assert shown == []
    window.session.keep_alive_inhibit_status.emit(missing)
    window.session.keep_alive_inhibit_status.emit(missing)
    assert shown == ["Keep-Alive cannot block sleep"]


# ── Float strips ───────────────────────────────────────────────────────────

def test_the_window_owns_the_strips(window):
    from utils.strips.controller import StripController
    strips = window.strips
    assert isinstance(strips, StripController)
    assert strips._session is window.session
    assert strips._keymap_manager is window.keymap_manager
    assert strips._started is True


def test_strips_are_shut_down_before_the_services(isolated, qapp, monkeypatch):
    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    order = []
    monkeypatch.setattr(win.strips, "shutdown", lambda: order.append("strips"))
    monkeypatch.setattr(win.session, "shutdown", lambda: order.append("session"))
    win.shutdown()
    assert order == ["strips", "session"]
    monkeypatch.undo()
    win._shutdown_complete = False
    _dispose(win, qapp)


def test_a_strip_can_open_the_window_on_settings_or_the_launcher(window, qapp):
    window.hide()
    window.strips.open_window_requested.emit("settings")
    assert window.isVisible()
    assert window.open_sheet_name() == SHEET_SETTINGS
    window.strips.open_window_requested.emit("launcher")
    assert window.open_sheet_name() is None
    window.open_sheet(SHEET_KEYSETS)
    window.showMinimized()
    window.strips.open_window_requested.emit("main")
    assert not window.isMinimized()
    assert window.open_sheet_name() == SHEET_KEYSETS        # "main" leaves it be


def test_a_strips_change_colour_opens_that_toons_look(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window.launch_tab, "open_appearance_for_toon",
                        lambda game, name: opened.append((game, name)) or True)
    window.open_sheet(SHEET_SETTINGS)
    window.hide()
    window.strips.appearance_requested.emit("ttr", "Flossbud")
    assert opened == [("ttr", "Flossbud")]
    assert window.isVisible()
    assert window.open_sheet_name() is None         # the editor is in the launcher


def test_a_look_saved_reaches_the_strips_as_well(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window.strips, "customization_changed",
                        lambda game, name: seen.append((game, name)))
    window.launch_tab.look_saved.emit("cc", "Moe")
    assert seen == [("cc", "Moe")]


def test_quit_from_a_strip_is_the_window_closing(window, isolated):
    window.quit_app()
    assert isolated == [1]
    assert window._shutdown_complete is True


def test_the_window_survives_strips_that_cannot_be_built(isolated, monkeypatch, qapp):
    from utils.launchpad_window import LaunchpadWindow
    import utils.strips.controller as controller

    def broken(*args, **kwargs):
        raise RuntimeError("no overlay backend")

    monkeypatch.setattr(controller.StripController, "__init__", broken)
    win = LaunchpadWindow()
    try:
        assert win.strips is None
        assert win.launch_tab.isWidgetType()
    finally:
        _dispose(win, qapp)


# ── Launcher port ──────────────────────────────────────────────────────────

def _add_account(window, game, username, label=""):
    creds = window.launch_tab.cred_manager
    assert creds.add_account(label=label, username=username, password="pw", game=game)
    window.launch_tab._reconcile_slots()
    window.launch_tab._render_current_view(game)
    return creds.get_accounts_metadata(game)[-1].id


def test_the_port_lists_the_launchers_accounts_and_follows_them(window):
    from utils.launcher_port import PortAccount
    port = window.launcher_port
    assert port.accounts() == []
    seen = []
    port.changed.connect(lambda: seen.append(1))
    ttr = _add_account(window, "ttr", "flossbud", label="Main")
    cc = _add_account(window, "cc", "clashmain")
    assert seen == [1, 1]
    assert port.accounts() == [
        PortAccount(ttr, "ttr", "Main", "idle", ""),
        PortAccount(cc, "cc", "clashmain", "idle", ""),
    ]


def test_the_port_reports_a_launch_in_progress(window):
    from services.ttr_login_service import LoginState
    port = window.launcher_port
    account_id = _add_account(window, "ttr", "flossbud")
    seen = []
    port.changed.connect(lambda: seen.append(1))
    window.launch_tab._slots["ttr"][account_id].state = LoginState.LOGGING_IN
    window.launch_tab._render_current_view("ttr")
    assert port.accounts()[0].state == "launching"
    assert seen == [1]


def test_the_port_launches_through_the_launcher(window, monkeypatch):
    launched = []
    monkeypatch.setattr(window.launch_tab, "_on_launch",
                        lambda game, account_id: launched.append((game, account_id)))
    account_id = _add_account(window, "cc", "clashmain")
    assert window.launcher_port.launch(account_id) is True
    assert launched == [("cc", account_id)]
    assert window.launcher_port.launch("nope") is False


def test_appearance_opens_on_the_named_toon_of_the_account_that_has_it(window):
    tab = window.launch_tab
    first = _add_account(window, "ttr", "one")
    second = _add_account(window, "ttr", "two")
    tab._recent_toons.record(first, "Flossbud", "ttr", dna="aa")
    tab._recent_toons.record(second, "Hector", "ttr", dna="bb")
    tab._recent_toons.record(second, "Linux", "ttr", dna="cc")     # shown: Linux
    tab._render_current_view("ttr")
    assert tab.open_appearance_for_toon("ttr", "Hector") is True
    sheet = tab.grandstand.appearance_sheet
    assert tab.grandstand.sheet.body() is sheet
    draft = sheet.draft() if callable(getattr(sheet, "draft", None)) else None
    if draft is not None:
        assert (draft.account_id, draft.toon_name) == (second, "Hector")
    assert tab.open_appearance_for_toon("ttr", "Nobody") is False
    assert tab.open_appearance_for_toon("ttr", "") is False


# ── Settings sheet ─────────────────────────────────────────────────────────

def test_settings_button_opens_the_real_settings_sheet(window, qapp):
    from utils.widgets.launchpad.settings_sheet import SettingsSheet
    window.header.buttons.buttons[SHEET_SETTINGS].click()
    sheet = window.sheet_host.current_content()
    assert isinstance(sheet, SettingsSheet) and sheet is window.settings_sheet
    header = window.sheet_host.panel.header
    assert header.title_label.text() == "Settings"
    assert header.sub_label.text() == sheet.sub()


def test_settings_tabs_retitle_the_sheet_only_while_it_is_open(window, qapp):
    sheet = window.settings_sheet
    header = window.sheet_host.panel.header
    window.open_sheet(SHEET_KEYSETS)
    before = header.sub_label.text()
    sheet.set_tab("logs")
    assert header.sub_label.text() == before             # Keysets is showing
    window.open_sheet(SHEET_SETTINGS)
    assert header.sub_label.text() == sheet.sub()
    sheet.set_tab("about")
    assert header.sub_label.text() == sheet.sub()
    sheet.set_tab("settings")


def test_the_logs_console_is_the_one_the_window_feeds(window):
    assert window.settings_sheet.logs_page.findChild(
        type(window.debug_tab.card)) is window.debug_tab.card
    window.settings_manager.set("show_debug_tab", True)
    window.log("[Test] a line for the console")           # must not raise


def test_main_reaches_the_settings_rows_by_the_old_name(window):
    rows = window.settings_sheet.rows
    assert window.settings_tab is rows
    assert callable(rows.apply_picked_install)
    assert rows._update_checker is window.update_checker
    assert rows._hotkey_accounts_provider() == \
        window.launch_tab.cred_manager.get_accounts_basic()


def test_a_theme_picked_in_settings_restyles_the_window_once(window, monkeypatch):
    calls = []
    original = window._apply_full_theme
    monkeypatch.setattr(window, "_apply_full_theme",
                        lambda: (calls.append(1), original())[1])
    window.settings_sheet.rows._on_theme_changed(1)       # light
    assert calls == [1]
    assert window._is_dark() is False
    window.settings_sheet.rows._on_theme_changed(2)       # dark
    assert calls == [1, 1]


def test_verbose_logging_toggle_in_settings_reaches_the_router(window):
    rows = window.settings_sheet.rows
    rows._on_logging_toggled(True)
    assert window.debug_tab.logging_enabled is True
    assert window.session.input_service.logging_enabled is True
    rows._on_logging_toggled(False)
    assert window.session.input_service.logging_enabled is False


def test_input_backend_change_restarts_the_router(window, monkeypatch):
    restarts = []
    monkeypatch.setattr(window.session, "restart_router", lambda: restarts.append(1))
    # Reconnect: the signal was bound to the original method object.
    window.settings_sheet.rows.input_backend_changed.connect(window.session.restart_router)
    window.settings_sheet.rows.input_backend_changed.emit()
    assert restarts


def test_clear_credentials_goes_to_the_launcher(window, monkeypatch):
    cleared = []
    monkeypatch.setattr(window.launch_tab, "clear_all_credentials",
                        lambda: cleared.append(1))
    window.settings_sheet.rows.clear_credentials_requested.emit()
    assert cleared == [1]


def test_hotkey_registration_failures_reach_the_settings_rows(window, monkeypatch):
    pushed = []
    monkeypatch.setattr(window.settings_sheet.rows, "set_hotkey_status", pushed.append)
    window.hotkeys.status_changed.emit({"service.toggle": "taken"})
    assert pushed == [{"service.toggle": "taken"}]


def test_the_sheet_follows_the_cards_rounded_corners(window):
    from utils.widgets.window_chrome_style import RADIUS_NORMAL, STROKE_INSET
    host = window.sheet_host
    assert (host._inset, host._bottom_radius) == (
        STROKE_INSET, RADIUS_NORMAL - STROKE_INSET)
    window._apply_window_corner_state(True, force=True)      # maximized: square
    assert (host._inset, host._bottom_radius) == (0, 0)
    window._apply_window_corner_state(False, force=True)


# ── Lifecycle ──────────────────────────────────────────────────────────────

def test_shutdown_stops_every_service_once(isolated, qapp):
    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    session, wm = win.session, win.window_manager
    assert session.input_service.running
    win.shutdown()
    win.shutdown()
    assert not session.input_service.running
    assert session._shut_down is True
    assert wm._running is False
    _dispose(win, qapp)


def test_closing_the_window_quits_the_app(isolated, qapp):
    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    win.close()
    assert isolated == [1]                      # the recorded quit requests
    assert win._shutdown_complete is True
    _dispose(win, qapp)
