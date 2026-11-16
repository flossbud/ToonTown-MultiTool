"""Settings sheet (launchpad handoff section 7), content for SlideSheetHost.

A chip row switches Settings / Logs / About.

Settings is every shipped Settings row, built by the same code the Settings
page uses (utils/widgets/settings_rows.SettingsRows) and regrouped:

- Features: Keep-Alive, Click Sync (with the ghost cursor rows), Hotkeys,
  Chat handling.
- Float strips: strip style, hide this window once toons are up, tray icon.
- Toontown Rewritten / Corporate Clash: the game rows that exist today.
- App: appearance, reduce motion, system title bar, updates, verbose logging,
  input backend, storage, macOS permissions.

"Start in Float UI" is dropped. The rows keep their handlers, so Keep-Alive
still asks for ToS consent and records it before it turns the flag on.

Logs mounts the app's existing logs console widget (passed in by the
window, which feeds it). About is the wordmark, version, a line and the
repository link.

Wiring for the window: `sheet.rows` is the SettingsRows instance; connect
its signals and setters exactly as main.py does for SettingsTab. Connect
`header_changed(title, sub)` to the host's set_header.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QToolButton, QWidget

from utils import settings_keys as sk
from utils.color_math import alpha
from utils.icon_factory import make_bolt_icon, make_strip_icon, make_window_icon
from utils.theme_manager import V2_ACCENTS, is_dark_palette
from utils.widgets.launchpad.material import (
    GLOW_PAD, GroupCard, PlainCard, SheetRow, SheetSegmented, SheetToggle,
    note_label, sheet_palette, sheet_stack,
)
from utils.widgets.settings_rows import SettingsRows

IDENTITY = "#3da343"
TITLE = "Settings"
TABS = (("settings", "Settings"), ("logs", "Logs"), ("about", "About"))
SUBS = {"settings": "App-wide preferences", "logs": "What the app has been doing",
        "about": "ToonTown MultiTool"}
REPO_URL = "https://github.com/flossbud/ToonTown-MultiTool"
ABOUT_LINE = ("A multitoon controller for Toontown Rewritten and Corporate Clash. "
              "Made by Flossbud.")

FEATURES = ("#0077ff", "Features")
STRIPS = ("#1fb8a6", "Float strips")
APP = ("#d4a017", "App")
GAME_COLORS = {"ttr": "#4A8FE7", "cc": "#F26D21"}

# Which shared card's rows go to which sheet group, in order.
FEATURE_CARDS = ("keep_alive", "click_sync", "hotkeys", "chat_handling")
APP_CARDS = ("appearance", "updates", "diagnostics", "storage", "macos")
DROPPED_CONTROLS = ("start_in_float_ui_switch",)


class _CardSink:
    """Stands in for a CardSurface while the shared builders run: keeps the
    card's rows, and passes header buttons and the sub line to the sheet."""

    def __init__(self, sheet: "SettingsSheet", card_id: str, title: str,
                 sub: str | None):
        self.card_id = card_id
        self.title = title
        self.sub = sub if sub and sub.strip() else None
        self.rows: list = []
        self._sheet = sheet

    def add_row(self, widget, stretch: int = 0) -> None:
        self.rows.append(widget)

    def add_header_button(self, button) -> None:
        self._sheet._card_header_button(self.card_id, button)

    def set_sub(self, text: str, *, color_override: str | None = None,
                rich_text: bool = False, mono: bool = False) -> None:
        self._sheet._card_sub(self.card_id, text, color_override, rich_text, mono)

    def set_sub_widget(self, widget) -> None:
        self.rows.insert(0, widget)

    def apply_theme(self, is_dark: bool, animate: bool = False) -> None:
        pass

    def pulse_highlight(self) -> None:
        pass


class _PageStub:
    """What the builders take as `page`: they insert each card before the
    last layout item. The sheet assembles cards itself, so this is inert."""

    class _Layout:
        def count(self) -> int:
            return 1

        def insertWidget(self, *_a, **_k) -> None:   # noqa: N802 (Qt name)
            pass

    def __init__(self):
        self._panel_layout = self._Layout()


class SheetSettingsRows(SettingsRows):
    """SettingsRows that builds the sheet material and hands its cards to the
    Settings sheet."""

    def __init__(self, sheet: "SettingsSheet", *args, is_dark: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self._sheet = sheet
        self._is_dark = is_dark
        self._card_id = None

    # Cards → sinks. Builders make a card, then its rows, so the rows that
    # follow belong to this card.
    def _new_card(self, card_id, *args, **kwargs):
        self._card_id = card_id
        return self._sheet._new_sink(card_id, kwargs.get("title", ""), kwargs.get("sub"))

    def _accent(self, accent_key: str) -> str:
        """A row control's colour in the sheet: rows that moved into App or a
        game card take that card's colour (the handoff colours Appearance
        with App's gold); Features rows keep their own (Keep-Alive orange,
        Click Sync pink, ...)."""
        if self._card_id in APP_CARDS:
            return APP[0]
        if self._card_id in GAME_COLORS:
            return GAME_COLORS[self._card_id]
        a = V2_ACCENTS.get(accent_key, V2_ACCENTS["blue"])
        return a["b"] if accent_key == "red" else a["c"]

    # Row factories → sheet material (same APIs as the Settings v2 parts).
    def _v2_row(self, label, helper=None):
        row = SheetRow(label, helper, is_dark=self._is_dark)
        self._v2_rows.append(row)
        return row

    def _v2_switch(self, checked, accent_key):
        sw = SheetToggle(bool(checked), self._accent(accent_key), is_dark=self._is_dark)
        sw._sheet_accent = sw._track_on
        self._v2_switches.append((sw, accent_key))
        return sw

    def _v2_segment(self, options, accent_key, stretch=False):
        seg = SheetSegmented(options, self._accent(accent_key), is_dark=self._is_dark,
                             stretch=stretch)
        seg._sheet_accent = seg._fill
        self._v2_segments.append((seg, accent_key))
        return seg

    def _apply_rows_theme(self, is_dark):
        self._is_dark = is_dark
        super()._apply_rows_theme(is_dark)
        # The shared theming sets Settings v2 colours; put the sheet's back.
        for sw, _key in self._v2_switches:
            if isinstance(sw, SheetToggle):
                sw.apply_theme(is_dark)
                sw.set_accent(sw._sheet_accent, sw._sheet_accent)
        for seg, _key in self._v2_segments:
            if isinstance(seg, SheetSegmented):
                seg.apply_sheet_theme(is_dark)
                seg.set_fill(seg._sheet_accent)


class _Chip(QToolButton):
    """h 30, radius 999; selected: blue 16 % fill, #3399ff border."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)

    def apply_theme(self, is_dark: bool) -> None:
        pal = sheet_palette(is_dark)
        on_text = "#ffffff" if is_dark else pal["text"]
        self.setStyleSheet(
            "QToolButton { background: transparent;"
            f" border: 1px solid {pal['border_card']}; border-radius: 15px;"
            f" color: {pal['text_secondary']}; font-size: 12px; font-weight: 600;"
            " padding: 0 14px; }"
            f"QToolButton:hover {{ border-color: {pal['border_light']}; }}"
            f"QToolButton:checked {{ background: {alpha('#3399ff', 0.16)};"
            f" border-color: #3399ff; color: {on_text}; }}")


class SettingsSheet(QWidget):
    """Content widget for the sheet host:
    host.open(sheet, sheet.IDENTITY, sheet.TITLE, sheet.sub())."""

    IDENTITY = IDENTITY
    TITLE = TITLE
    header_changed = Signal(str, str)        # title, sub
    tab_changed = Signal(str)

    def __init__(self, settings_manager, keymap_manager=None, credentials_manager=None,
                 logs_widget: QWidget | None = None, is_dark: bool | None = None,
                 parent=None):
        super().__init__(parent)
        self._sm = settings_manager
        self._is_dark = is_dark_palette() if is_dark is None else bool(is_dark)
        self._tab = "settings"
        self._sinks: dict[str, _CardSink] = {}
        self._header_buttons: dict[str, list] = {}
        self._game_cards: dict[str, GroupCard] = {}
        self._path_notes: dict[str, QLabel] = {}
        self._pending_sub: dict[str, tuple] = {}
        self._captions: list[QLabel] = []
        self._dropped = QWidget(self)            # keeps dropped rows alive, hidden
        self._dropped.hide()

        lay = sheet_stack(self)
        chips = QWidget(self)
        chips.setStyleSheet("background: transparent;")
        cl = QHBoxLayout(chips)
        cl.setContentsMargins(GLOW_PAD, GLOW_PAD, GLOW_PAD, GLOW_PAD)
        cl.setSpacing(6)
        self.chips: dict[str, _Chip] = {}
        for key, label in TABS:
            chip = _Chip(label, chips)
            chip.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            self.chips[key] = chip
            cl.addWidget(chip)
        cl.addStretch(1)
        lay.addWidget(chips)


        # Settings page: the shared rows, regrouped.
        self.rows = SheetSettingsRows(self, settings_manager, keymap_manager,
                                      credentials_manager, dialog_parent=self,
                                      is_dark=self._is_dark)
        stub = _PageStub()
        self.rows._build_general_page(stub)
        self.rows._build_games_page(stub)
        self.rows._build_features_page(stub)
        self.rows._build_advanced_page(stub)
        # Pages are shown one at a time; a hidden page takes no space.
        self.settings_page = self._build_settings_page()
        self.logs_page = self._build_logs_page(logs_widget)
        self.about_page = self._build_about_page()
        self.pages = {"settings": self.settings_page, "logs": self.logs_page,
                      "about": self.about_page}
        for page in self.pages.values():
            page.setParent(self)
            lay.addWidget(page)

        self.set_tab("settings")
        self.apply_theme(self._is_dark)

    # ── public API ──────────────────────────────────────────────────────
    def tab(self) -> str:
        return self._tab

    def sub(self) -> str:
        return SUBS[self._tab]

    def set_tab(self, key: str) -> None:
        if key not in SUBS:
            return
        changed = key != self._tab
        self._tab = key
        for k, chip in self.chips.items():
            chip.setChecked(k == key)
        for k, page in self.pages.items():
            page.setVisible(k == key)
        self.header_changed.emit(TITLE, SUBS[key])
        if changed:
            self.tab_changed.emit(key)

    def keep_alive_row(self):
        sink = self._sinks.get("keep_alive")
        return sink.rows[0] if sink and sink.rows else None

    def highlight_keep_alive(self) -> None:
        """Show the Settings tab and scroll the Keep-Alive row into view
        (the sheet's stand-in for SettingsTab.highlight_keep_alive_group)."""
        self.set_tab("settings")
        row = self.keep_alive_row()
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if row is not None and w is not None:
            w.ensureWidgetVisible(row, 0, 40)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = bool(is_dark)
        pal = sheet_palette(self._is_dark)
        for chip in self.chips.values():
            chip.apply_theme(self._is_dark)
        for card in self._cards_in_order():
            card.apply_theme(self._is_dark)
        self.rows._apply_rows_theme(self._is_dark)
        for row in self._strip_rows:
            row.apply_theme(self._is_dark)
        self._strip_style.apply_sheet_theme(self._is_dark)
        for t in (self._hide_toggle, self._tray_toggle):
            t.apply_theme(self._is_dark)
        for lbl in self._captions:
            lbl.setStyleSheet(
                f"QLabel {{ font-size: 10px; font-weight: 700; color: {pal['text_muted']};"
                " letter-spacing: 1px; background: transparent; border: none;"
                " padding: 4px 2px 0 2px; }")
        for game, lbl in self._path_notes.items():
            self._style_path_note(game)
        self.about_card.apply_theme(self._is_dark)
        self._style_about()
        logs = getattr(self, "logs_widget", None)
        if logs is not None and hasattr(logs, "apply_theme"):
            logs.apply_theme(self._is_dark)
        if self._logs_note is not None:
            self._logs_note.setStyleSheet(
                f"QLabel {{ font-size: 11px; color: {pal['text_muted']};"
                " background: transparent; border: none; }")

    # ── sinks (called by the shared builders) ───────────────────────────
    def _new_sink(self, card_id: str, title: str, sub) -> _CardSink:
        sink = _CardSink(self, card_id, title, sub)
        self._sinks[card_id] = sink
        return sink

    def _card_header_button(self, card_id: str, button) -> None:
        self._header_buttons.setdefault(card_id, []).append(button)
        card = self._game_cards.get(card_id)
        if card is not None:
            card.add_meta_widget(button)

    def _card_sub(self, card_id, text, color_override, rich_text, mono) -> None:
        self._pending_sub[card_id] = (text, color_override, rich_text, mono)
        if card_id in self._path_notes:
            self._style_path_note(card_id)

    def _style_path_note(self, game: str) -> None:
        lbl = self._path_notes[game]
        text, color, rich, mono = self._pending_sub.get(game, ("", None, False, False))
        pal = sheet_palette(self._is_dark)
        lbl.setTextFormat(Qt.RichText if rich else Qt.PlainText)
        lbl.setText(text)
        lbl.setVisible(bool(text and text.strip()))
        family = ('font-family: "JetBrains Mono", Consolas, Menlo, "DejaVu Sans Mono",'
                  " monospace;" if mono else "")
        lbl.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {color or pal['meta']}; {family}"
            " background: transparent; border: none; }")

    # ── page builders ───────────────────────────────────────────────────
    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        self._captions.append(lbl)
        return lbl

    def _take_rows(self, card_id: str) -> list:
        sink = self._sinks.get(card_id)
        if sink is None:
            return []
        rows = []
        for row in sink.rows:
            ctrl = getattr(row, "control_widget", None)
            if ctrl is not None and ctrl.objectName() in DROPPED_CONTROLS:
                row.setParent(self._dropped)
                continue
            rows.append(row)
        return rows

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = sheet_stack(page)
        white = QColor("#ffffff")
        self._cards: dict[str, GroupCard] = {}

        # Features
        features = GroupCard(FEATURES[0], FEATURES[1], make_bolt_icon(15, white),
                             is_dark=self._is_dark)
        for card_id in FEATURE_CARDS:
            sink = self._sinks.get(card_id)
            if sink is None:
                continue
            features.add_row(self._caption(sink.title))
            if sink.sub:
                features.add_row(note_label(sink.sub, self._is_dark))
            for row in self._take_rows(card_id):
                features.add_row(row)
        lay.addWidget(features)
        self._cards["features"] = features

        # Float strips (the three new keys)
        strips = GroupCard(STRIPS[0], STRIPS[1], make_strip_icon(15, white),
                           is_dark=self._is_dark)
        style_row = SheetRow("Strip style", "How the strip on each game window is drawn.",
                             is_dark=self._is_dark)
        self._strip_style = SheetSegmented(["Neon", "Flat"], STRIPS[0], is_dark=self._is_dark)
        current = sk.normalize_float_strip_style(self._sm.get(sk.FLOAT_STRIP_STYLE))
        self._strip_style.setCurrentIndex(sk.FLOAT_STRIP_STYLE_VALUES.index(current))
        self._strip_style.index_changed.connect(
            lambda i: self._sm.set(sk.FLOAT_STRIP_STYLE, sk.FLOAT_STRIP_STYLE_VALUES[i]))
        style_row.set_control(self._strip_style)
        hide_row = SheetRow("Hide this window once toons are up",
                            "Bring it back from the home block or the tray icon.",
                            is_dark=self._is_dark)
        self._hide_toggle = SheetToggle(
            bool(self._sm.get(sk.HIDE_WINDOW_WHEN_TOONS_UP,
                              sk.HIDE_WINDOW_WHEN_TOONS_UP_DEFAULT)),
            STRIPS[0], is_dark=self._is_dark)
        self._hide_toggle.toggled.connect(
            lambda v: self._sm.set(sk.HIDE_WINDOW_WHEN_TOONS_UP, bool(v)))
        hide_row.set_control(self._hide_toggle)
        tray_row = SheetRow("Tray icon",
                            "Keeps MultiTool reachable when every strip is covered.",
                            is_dark=self._is_dark)
        self._tray_toggle = SheetToggle(
            bool(self._sm.get(sk.TRAY_ICON, sk.TRAY_ICON_DEFAULT)), STRIPS[0],
            is_dark=self._is_dark)
        self._tray_toggle.toggled.connect(lambda v: self._sm.set(sk.TRAY_ICON, bool(v)))
        tray_row.set_control(self._tray_toggle)
        self._strip_rows = [style_row, hide_row, tray_row]
        for row in self._strip_rows:
            strips.add_row(row)
        lay.addWidget(strips)
        self._cards["strips"] = strips

        # Games: one card per game, as the Accounts sheet does.
        from utils.asset_paths import asset_path
        for game, card_id in (("ttr", "ttr"), ("cc", "cc")):
            sink = self._sinks.get(card_id)
            if sink is None:
                continue
            logo = QPixmap(asset_path(f"{game}.png"))
            card = GroupCard(GAME_COLORS[game], sink.title, None,
                             is_dark=self._is_dark, logo=logo)
            self._game_cards[card_id] = card
            for button in self._header_buttons.get(card_id, []):
                card.add_meta_widget(button)
            note = note_label("", self._is_dark)
            note.setWordWrap(True)
            self._path_notes[card_id] = note
            card.add_row(note)
            self._style_path_note(card_id)
            for row in self._take_rows(card_id):
                card.add_row(row)
            lay.addWidget(card)
            self._cards[card_id] = card

        # App
        app = GroupCard(APP[0], APP[1], make_window_icon(15, white), is_dark=self._is_dark)
        for card_id in APP_CARDS:
            for row in self._take_rows(card_id):
                label = getattr(row, "label_widget", None)
                if label is not None and label.text() == "Enable Logging":
                    # Logs is always a chip now; the row only switches the
                    # extra debug logging.
                    label.setText("Verbose logging")
                app.add_row(row)
        lay.addWidget(app)
        self._cards["app"] = app
        return page

    def _cards_in_order(self) -> list:
        return list(getattr(self, "_cards", {}).values())

    def _build_logs_page(self, logs_widget) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = sheet_stack(page)
        self.logs_widget = logs_widget
        self._logs_note = None
        if logs_widget is not None:
            logs_widget.setParent(page)
            lay.addWidget(logs_widget)
        else:
            self._logs_note = QLabel("Logs appear here while the app is running.")
            self._logs_note.setContentsMargins(GLOW_PAD, GLOW_PAD, GLOW_PAD, GLOW_PAD)
            lay.addWidget(self._logs_note)
        return page

    def _build_about_page(self) -> QWidget:
        from utils import build_info
        from utils.open_url import open_url
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = sheet_stack(page)
        self.about_card = PlainCard(is_dark=self._is_dark)
        self._wordmark = QLabel()
        self._wordmark.setAlignment(Qt.AlignHCenter)
        self.about_card.add_row(self._wordmark)
        self._version = QLabel(build_info.version_string())
        self._version.setAlignment(Qt.AlignHCenter)
        self.about_card.add_row(self._version)
        self._about_line = QLabel(ABOUT_LINE)
        self._about_line.setWordWrap(True)
        self._about_line.setAlignment(Qt.AlignHCenter)
        self.about_card.add_row(self._about_line)
        self._repo = QLabel()
        self._repo.setAlignment(Qt.AlignHCenter)
        self._repo.setTextFormat(Qt.RichText)
        self._repo.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._repo.linkActivated.connect(open_url)
        self.about_card.add_row(self._repo)
        lay.addWidget(self.about_card)
        return page

    def _style_about(self) -> None:
        pal = sheet_palette(self._is_dark)
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
        fname = "ttmt_logo_textonly.png" if self._is_dark else "ttmt_logo_textonly_shadow.png"
        src = QPixmap(os.path.join(here, "assets", "logos", fname))
        if not src.isNull():
            self._wordmark.setPixmap(src.scaledToHeight(64, Qt.SmoothTransformation))
        self._version.setStyleSheet(
            'QLabel { font-family: "JetBrains Mono", Consolas, Menlo, "DejaVu Sans Mono",'
            f" monospace; font-size: 12px; color: {pal['text_muted']};"
            " background: transparent; border: none; }")
        self._about_line.setStyleSheet(
            f"QLabel {{ font-size: 12px; color: {pal['text_secondary']};"
            " background: transparent; border: none; }")
        link = "#6ba8f0" if self._is_dark else "#1d4ed8"
        self._repo.setText(f'<a href="{REPO_URL}" style="color:{link};">'
                           "github.com/flossbud/ToonTown-MultiTool</a>")
        self._repo.setStyleSheet(
            "QLabel { font-size: 12px; background: transparent; border: none; }")

    # ── events ──────────────────────────────────────────────────────────
    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Same as SettingsTab.showEvent: accounts may have changed while the
        # sheet was closed, so the launch-slot pickers repopulate.
        if getattr(self.rows, "_hotkey_accounts_provider", None) is not None:
            self.rows._rebuild_hotkey_slot_rows()
