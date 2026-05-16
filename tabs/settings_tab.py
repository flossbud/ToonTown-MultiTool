from __future__ import annotations

import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QFileDialog,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from utils.theme_manager import apply_theme, get_theme_colors, resolve_theme
from utils.shared_widgets import IOSToggle
from utils.widgets import install_modern_scrollbar
from services.ttr_login_service import find_engine_path, get_engine_executable_name
from services.cc_login_service import (
    find_cc_engine_path,
    get_cc_engine_executable_name,
    discover_cc_installs,
)
from services.wine_runtimes import install_signature
from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete"
}


def _elevated_control_palette(c: dict, is_dark: bool) -> dict:
    """Resting + hover colors for controls living inside a `SettingsGroup`.

    The block paints at an elevated tone (`#333` in dark, `bg_card_inner`
    in light), so the global `btn_bg` / `border_muted` tokens — sized for
    controls on `bg_app` — collide with the block surface (dark mode:
    identical hex) or leave no visible edge (light mode: border == fill).
    Step the controls one tone clear of the block, and use a tonal-only
    hover (Material state-layer style) instead of a brand-color swap —
    Browse / Auto-detect / etc. are tertiary utility actions, not CTAs.
    """
    if is_dark:
        return {
            "bg": "#3a3a3a",
            "border": "#4a4a4a",
            "hover_bg": "#454545",
            "hover_border": "#5a5a5a",
        }
    return {
        "bg": c["btn_bg"],
        "border": c["border_input"],
        "hover_bg": c["btn_hover"],
        "hover_border": c["border_input"],
    }


# ── Settings Row Types ─────────────────────────────────────────────────────────

class SettingsRow(QFrame):
    """Single flat settings row: label + optional sublabel on the left,
    control widget on the right. Paints a 1px bottom divider unless it is
    the last row in its enclosing block."""

    HEIGHT_NO_SUB = 48
    HEIGHT_WITH_SUB = 60

    def __init__(self, label: str, sublabel: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._sublabel = sublabel
        self._is_last_in_block = False
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumHeight(
            self.HEIGHT_WITH_SUB if sublabel else self.HEIGHT_NO_SUB
        )

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 0, 14, 0)
        self._layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        self.label_widget.setMinimumWidth(1)
        text_col.addWidget(self.label_widget)

        if sublabel:
            self.sub_widget = QLabel(sublabel)
            self.sub_widget.setStyleSheet("background: transparent; border: none;")
            self.sub_widget.setWordWrap(True)
            self.sub_widget.setMinimumWidth(1)
            text_col.addWidget(self.sub_widget)

        self._layout.addLayout(text_col, 1)

    def add_control(self, widget):
        self._layout.addWidget(widget)

    def set_leading_indicator(self, token_name: str):
        """Insert a colored pill at the start of the row.

        `token_name` is a theme-token key (e.g. "game_pill_ttr"); the pill
        resolves it through the palette on apply_theme."""
        self._leading_pill = _LeadingPill(token_name, self)
        self._layout.insertWidget(0, self._leading_pill)

    def set_last_in_block(self, is_last: bool):
        self._is_last_in_block = is_last
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def apply_theme(self, c, is_dark):
        self.label_widget.setStyleSheet(
            f"font-size: 13px; color: {c['text_primary']}; "
            f"background: transparent; border: none;"
        )
        if hasattr(self, "sub_widget"):
            self.sub_widget.setStyleSheet(
                f"font-size: 11.5px; color: {c['text_muted']}; "
                f"background: transparent; border: none;"
            )
        self._c = c
        self._is_dark = is_dark
        self.update()
        if hasattr(self, "_leading_pill"):
            self._leading_pill.apply_theme(c, is_dark)

    def paintEvent(self, e):
        if not hasattr(self, "_c"):
            return
        p = QPainter(self)
        # Hover overlay: subtle ambient highlight, no cursor change.
        if self._hovered:
            overlay = QColor("#ffffff" if self._is_dark else "#0f172a")
            overlay.setAlpha(8 if self._is_dark else 10)
            p.setRenderHint(QPainter.Antialiasing, False)
            p.fillRect(self.rect(), overlay)
        # Bottom divider (unchanged behavior).
        if not self._is_last_in_block:
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
            w, h = self.width(), self.height()
            p.drawLine(14, h - 1, w - 14, h - 1)
        p.end()


class ToggleRow(SettingsRow):
    toggled = Signal(bool)

    def __init__(self, label: str, checked: bool, sublabel: str = "", parent=None):
        super().__init__(label, sublabel, parent)
        self.toggle = IOSToggle(checked)
        self.toggle.toggled.connect(self.toggled.emit)
        self.add_control(self.toggle)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        self.toggle.mousePressEvent(e)

    def isChecked(self):
        return self.toggle.isChecked()

    def setChecked(self, val):
        self.toggle.setChecked(val)


class DropdownRow(SettingsRow):
    index_changed = Signal(int)

    def __init__(self, label: str, options: list, current_index: int = 0, sublabel: str = "", parent=None):
        super().__init__(label, sublabel, parent)
        self._options = options
        self.combo = QComboBox()
        self.combo.addItems(options)
        self.combo.setCurrentIndex(current_index)
        self.combo.setFixedWidth(150)
        self.combo.currentIndexChanged.connect(self.index_changed.emit)
        self.add_control(self.combo)

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        p = _elevated_control_palette(c, is_dark)
        self.combo.setStyleSheet(f"""
            QComboBox {{
                background: {p['bg']};
                color: {c['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 13px;
            }}
            QComboBox:hover {{
                background: {p['hover_bg']};
                border: 1px solid {p['hover_border']};
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {c['bg_card_inner']};
                color: {c['text_primary']};
                selection-background-color: {p['bg']};
                border-radius: 8px;
            }}
        """)

    def currentIndex(self):
        return self.combo.currentIndex()

    def setCurrentIndex(self, idx):
        self.combo.setCurrentIndex(idx)

    def findText(self, text):
        return self.combo.findText(text)


class ButtonRow(SettingsRow):
    """Row with a single right-aligned QPushButton. Optional destructive
    styling (red outline) for irreversible actions."""

    clicked = Signal()

    def __init__(self, label: str, sublabel: str = "",
                 button_text: str = "...", destructive: bool = False,
                 parent=None):
        super().__init__(label, sublabel, parent)
        self._destructive = destructive
        self.button = QPushButton(button_text)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setFixedHeight(28)
        self.button.clicked.connect(self.clicked.emit)
        self.add_control(self.button)

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        if self._destructive:
            self.button.setStyleSheet("""
                QPushButton {
                    color: #ff3b30;
                    font-weight: bold;
                    background: transparent;
                    border: 1px solid #ff3b30;
                    border-radius: 6px;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background: rgba(255, 59, 48, 0.1);
                }
            """)
        else:
            p = _elevated_control_palette(c, is_dark)
            self.button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {p['bg']};
                    color: {c['text_secondary']};
                    border: 1px solid {p['border']};
                    border-radius: 6px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background-color: {p['hover_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {p['hover_border']};
                }}
            """)


class GamePathRow(SettingsRow):
    """Reusable game path row — parameterized for TTR, CC, or any future game."""

    def __init__(self, settings_manager, settings_key: str,
                 exe_name_fn, find_path_fn, label: str = "Game Path",
                 parent=None):
        super().__init__(label, "Not configured", parent)
        # Game identity pill — TTR violet, CC blue.
        if settings_key == "ttr_engine_dir":
            self.set_leading_indicator("game_pill_ttr")
        elif settings_key == "cc_engine_dir":
            self.set_leading_indicator("game_pill_cc")
        self.settings_manager = settings_manager
        self._settings_key = settings_key
        self._approval_key = f"{settings_key}_approved_custom_dir"
        self._exe_name_fn = exe_name_fn
        self._find_path_fn = find_path_fn

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setFixedHeight(28)
        self.browse_btn.clicked.connect(self._browse)
        btn_lay.addWidget(self.browse_btn)

        self.detect_btn = QPushButton("Auto-detect")
        self.detect_btn.setCursor(Qt.PointingHandCursor)
        self.detect_btn.setFixedHeight(28)
        self.detect_btn.clicked.connect(self._auto_detect)
        btn_lay.addWidget(self.detect_btn)

        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent;")
        btn_container.setLayout(btn_lay)
        self.add_control(btn_container)

        current_path = self.settings_manager.get(self._settings_key, "")
        if not current_path:
            self._auto_detect()
        else:
            self._refresh_display(current_path)

        self.needs_pick: bool = False
        self._cc_installs: list = []
        if settings_key == "cc_engine_dir":
            self._cc_installs = discover_cc_installs()
            stored_sig = self.settings_manager.get(
                CC_ENGINE_INSTALL_SIGNATURE, ""
            ) if self.settings_manager else ""
            sig_match = any(
                install_signature(i) == stored_sig
                for i in self._cc_installs
            ) if stored_sig else False
            if len(self._cc_installs) > 1 and not sig_match:
                self.needs_pick = True

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        self._palette = c
        self._is_dark = is_dark
        p = _elevated_control_palette(c, is_dark)
        btn_style = f"""
            QPushButton {{
                background-color: {p['bg']};
                color: {c['text_secondary']};
                border: 1px solid {p['border']};
                border-radius: 6px; padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {p['hover_bg']};
                color: {c['text_primary']};
                border: 1px solid {p['hover_border']};
            }}
        """
        self.browse_btn.setStyleSheet(btn_style)
        self.detect_btn.setStyleSheet(btn_style)
        if getattr(self, "needs_pick", False):
            orange = c.get("accent_orange", "#c47a2a")
            orange_border = c.get("accent_orange_border", "#e0943a")
            self.detect_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {p['bg']};
                    color: {orange};
                    border: 1px solid {orange_border};
                    border-radius: 6px; padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {p['hover_bg']};
                    color: {orange};
                    border: 1px solid {orange_border};
                }}
                """
            )

    def _refresh_display(self, path: str, error: bool = False):
        if not path:
            self.sub_widget.setText("Not found. Click Browse or Auto-detect.")
            self.sub_widget.setStyleSheet("font-size: 12px; color: #E05252; background: transparent; border: none;")
        elif error:
            self.sub_widget.setText(path)
            self.sub_widget.setStyleSheet("font-size: 12px; color: #E05252; background: transparent; border: none;")
        else:
            home = os.path.expanduser("~")
            display = path.replace(home, "~") if path.startswith(home) else path
            self.sub_widget.setText(display)
            self.sub_widget.setStyleSheet("font-size: 12px; color: #56c856; background: transparent; border: none;")

    def _browse(self):
        exe_name = self._exe_name_fn()
        dir_path = QFileDialog.getExistingDirectory(
            self, f"Select {exe_name} Folder",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if dir_path:
            engine = os.path.join(dir_path, exe_name)
            if os.path.isfile(engine):
                self.settings_manager.set(self._settings_key, dir_path)
                self.settings_manager.set(self._approval_key, os.path.realpath(dir_path))
                self._refresh_display(dir_path)
            else:
                self._refresh_display(f"{exe_name} not found in that folder", error=True)

    def _auto_detect(self):
        if self._settings_key == "cc_engine_dir":
            cc_installs = getattr(self, "_cc_installs", None)
            if cc_installs and len(cc_installs) > 1:
                # Multi-install case — always open the picker so the user
                # can pick (when needs_pick) or change their mind (when not).
                # This is what eliminates the silent cc_engine_dir clobber
                # when re-clicking Auto-detect on a resolved row.
                self._open_picker(cc_installs)
                return
        path = self._find_path_fn()
        if path:
            self.settings_manager.set(self._settings_key, path)
            self.settings_manager.set(self._approval_key, "")
            cc_installs = getattr(self, "_cc_installs", None)
            if (
                self._settings_key == "cc_engine_dir"
                and cc_installs is not None
                and len(cc_installs) == 1
            ):
                # Single-install case — record signature for stability.
                self.settings_manager.set(
                    CC_ENGINE_INSTALL_SIGNATURE,
                    install_signature(cc_installs[0]),
                )
            self._refresh_display(path)
        else:
            self._refresh_display("Could not auto-detect. Click Browse.", error=True)

    def _open_picker(self, installs):
        from utils.widgets.cc_install_picker import CCInstallPickerDialog
        dlg = CCInstallPickerDialog(installs, parent=self.window())
        if dlg.exec() == dlg.Accepted:
            picked = dlg.selected_install()
            if picked:
                self._apply_picked_install(picked)

    def _apply_picked_install(self, install):
        path = os.path.dirname(install.exe_path)
        self.settings_manager.set(self._settings_key, path)
        self.settings_manager.set(self._approval_key, "")
        self.settings_manager.set(
            CC_ENGINE_INSTALL_SIGNATURE,
            install_signature(install),
        )
        self.needs_pick = False
        self._refresh_display(path)
        # Force re-application of the standard (non-glow) button style.
        if hasattr(self, "_palette"):
            self.apply_theme(self._palette, getattr(self, "_is_dark", True))


class CompatRuntimeRow(SettingsRow):
    """Row that shows the active CC install's compatibility runtime.

    For steam-proton installs on Linux, a Change button opens the
    compat-picker dialog and persists the user's choice in
    cc_steam_proton_override. For other launcher types, the row is
    read-only (just shows the detected runner). On Windows, the row
    is hidden entirely (native launching only).
    """

    LABEL = "Compatibility runtime"

    def __init__(self, settings_manager, get_active_install, parent=None):
        super().__init__(self.LABEL, "", parent=parent)
        self.settings_manager = settings_manager
        self._get_active_install = get_active_install
        self.is_platform_hidden = sys.platform == "win32"

        if self.is_platform_hidden:
            self.hide()
            return

        # Build the value label + Change button as a single container
        # widget, then slot it via add_control (the real SettingsRow API).
        self.value_label = QLabel("")
        self.value_label.setObjectName("compat_runtime_value")
        self.change_button = QPushButton("Change…")
        self.change_button.setObjectName("compat_runtime_change")
        self.change_button.setCursor(Qt.PointingHandCursor)
        self.change_button.setFixedHeight(28)
        self.change_button.clicked.connect(self._on_change_clicked)

        ctrl_lay = QHBoxLayout()
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(8)
        ctrl_lay.addWidget(self.value_label, 1)
        ctrl_lay.addWidget(self.change_button, 0)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container.setLayout(ctrl_lay)
        self.add_control(container)

        if self.settings_manager is not None:
            self.settings_manager.on_change(self._on_setting_changed)
        self.refresh()

    def refresh(self):
        """Recompute the row state from the active install + override."""
        if self.is_platform_hidden:
            return
        install = self._get_active_install() if self._get_active_install else None
        if install is None:
            self.hide()
            return
        self.show()

        if install.launcher != "steam-proton":
            self.value_label.setText(self._readonly_label(install))
            self.value_label.setStyleSheet("")  # default theme
            self.change_button.hide()
            return

        self.change_button.show()
        from services.cc_launcher import _resolve_effective_proton
        chosen = _resolve_effective_proton(install, self.settings_manager)
        if chosen is None:
            self.value_label.setText("No Steam Proton found")
            self.value_label.setStyleSheet("color: #c0392b;")  # warning
            self.change_button.setEnabled(False)
            return

        self.change_button.setEnabled(True)
        display = self._display_name_for(chosen)
        override = (self.settings_manager.get("cc_steam_proton_override", "")
                    if self.settings_manager else "")
        suffix = "(custom)" if override else "(Steam default)"
        self.value_label.setText(f"{display} {suffix}")
        self.value_label.setStyleSheet("")

    @staticmethod
    def _readonly_label(install):
        if install.launcher == "bottles":
            runner = (install.metadata.get("bottle_display_name")
                      or install.metadata.get("bottle_name") or "(unknown)")
            return f"Bottles · {runner}"
        if install.launcher == "lutris":
            # Lutris pins wine version per-game inside its YAML config, but
            # _parse_lutris_yaml only surfaces lutris_slug / lutris_name in
            # metadata today. Show the game name as the next best identifier.
            name = install.metadata.get("lutris_name") or install.metadata.get("lutris_slug") or "(unknown)"
            return f"Lutris · {name}"
        if install.launcher == "wine":
            return "Wine · system wine"
        if install.launcher == "native":
            return "Native (no compatibility layer)"
        return install.launcher

    @staticmethod
    def _display_name_for(proton_dir: str) -> str:
        from services.steam_proton_tools import enumerate_proton_tools
        for tool in enumerate_proton_tools():
            if tool.proton_dir == proton_dir:
                return tool.display_name
        return os.path.basename(proton_dir.rstrip(os.sep))

    def _on_setting_changed(self, key, _value):
        if key == "cc_steam_proton_override" or key == "cc_engine_dir":
            self.refresh()

    def _on_change_clicked(self):
        from services.steam_proton_tools import enumerate_proton_tools
        from utils.widgets.cc_compat_picker import CCCompatPickerDialog
        install = self._get_active_install() if self._get_active_install else None
        if install is None or install.launcher != "steam-proton":
            return
        tools = enumerate_proton_tools()
        override = (self.settings_manager.get("cc_steam_proton_override", "")
                    if self.settings_manager else "")
        from services.cc_launcher import _resolve_effective_proton
        resolved = _resolve_effective_proton(install, self.settings_manager) or ""
        default_display = self._display_name_for(resolved) if resolved else "(none installed)"
        dlg = CCCompatPickerDialog(
            tools=tools,
            current_override=override,
            steam_default_display=default_display,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        chosen = dlg.chosen_override()
        if chosen is None:
            return
        if self.settings_manager is not None:
            self.settings_manager.set("cc_steam_proton_override", chosen)
        self.refresh()


# ── Section Group ──────────────────────────────────────────────────────────────

class SettingsGroup(QWidget):
    """Soft-surface section block. Paints a rounded fill behind its rows
    and renders an optional sentence-case title above the block."""

    CORNER_RADIUS = 12

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setContentsMargins(2, 0, 0, 8)
            layout.addWidget(self.title_label)

        # Shadow wrapper — `_block_wrapper` hosts a childless shadow caster
        # behind `_block`. The real block stays effect-free so its custom
        # paintEvent and child rows render normally.
        self._block_wrapper = _SectionBlockWrapper(self)
        wrapper_layout = QVBoxLayout(self._block_wrapper)
        wrapper_layout.setContentsMargins(
            _SectionBlockWrapper.MARGIN_X,
            _SectionBlockWrapper.MARGIN_TOP,
            _SectionBlockWrapper.MARGIN_X,
            _SectionBlockWrapper.MARGIN_BOTTOM,
        )
        wrapper_layout.setSpacing(0)

        self._block = _SectionBlock(self._block_wrapper)
        self._rows_layout = QVBoxLayout(self._block)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        wrapper_layout.addWidget(self._block)

        layout.addWidget(self._block_wrapper)

    def add_row(self, row):
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._refresh_last_row()

    def _refresh_last_row(self):
        for i, row in enumerate(self._rows):
            row.set_last_in_block(i == len(self._rows) - 1)

    def apply_theme(self, c, is_dark):
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; font-style: normal; "
                f"letter-spacing: 0.15px; "
                f"color: {c['text_primary']}; background: transparent;"
            )
        self._block_wrapper.apply_theme(c, is_dark)
        self._block.apply_theme(c, is_dark)
        for row in self._rows:
            row.apply_theme(c, is_dark)


class _SectionBlock(QFrame):
    """Inner block widget — paints the rounded soft-surface fill that backs
    the rows. Split out so the rounded fill lives on its own widget and
    doesn't interfere with the group's title-above-block layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = None
        self._is_dark = True

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Override the bg_card_inner / border_card tokens in dark mode —
        # they're only ~8% lighter than bg_app, which doesn't read as a
        # distinct elevated surface against the page. In light mode the
        # tokens work as-is (bg_card_inner is properly darker than bg_app).
        if self._is_dark:
            fill_color = "#333333"
            border_color = "#4a4a4a"
        else:
            fill_color = self._c.get("bg_card_inner", "#f1f5f9")
            border_color = self._c.get("border_card", "#e2e8f0")

        pen = QPen(QColor(border_color))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(QColor(fill_color))
        r = float(SettingsGroup.CORNER_RADIUS)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), r, r
        )
        p.end()


class _SectionBlockWrapper(QWidget):
    """Transparent wrapper that hosts a blurred shadow behind its inner
    `_SectionBlock` child.

    The effect lives on a simple, childless shadow caster instead of the real
    block. Applying effects to the block itself breaks custom painting with
    child rows, while painting the shadow as filled concentric rects creates
    visible bands. This keeps the real block plain and lets Qt blur one clean
    rounded silhouette.
    """

    MARGIN_X = 28
    MARGIN_TOP = 16
    MARGIN_BOTTOM = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._c = None
        self._shadow_live = True
        self.setObjectName("settings_section_wrapper")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent; border: none;")

        self._shadow = _SectionBlockShadow(self)
        self._shadow.lower()
        self._shadow_effect = QGraphicsDropShadowEffect(self._shadow)
        self._shadow_effect.setBlurRadius(28)
        self._shadow_effect.setOffset(0, 6)
        self._shadow.setGraphicsEffect(self._shadow_effect)

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        color = QColor(0, 0, 0) if is_dark else QColor(15, 23, 42)
        color.setAlpha(90 if is_dark else 36)
        self._shadow_effect.setColor(color)
        self._shadow.apply_theme(c, is_dark)
        self._sync_shadow_geometry()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_shadow_geometry()

    def set_shadow_live(self, live: bool):
        self._shadow_live = live
        self._shadow.setVisible(live)
        if live:
            self._sync_shadow_geometry()

    def _sync_shadow_geometry(self):
        # Z-order is set once at construction (shadow is created before the
        # block is added to the layout, so it's naturally below). Calling
        # lower()/raise_() per resize forces full repaints of the block and
        # every row child each animation frame, which destroys the collapse
        # animation's frame budget.
        if not self._shadow_live:
            return
        layout = self.layout()
        if layout is None or layout.count() == 0:
            return
        block_widget = layout.itemAt(0).widget()
        if block_widget is None:
            return
        self._shadow.setGeometry(block_widget.geometry())


class _SectionBlockShadow(QFrame):
    """Childless silhouette used only as the source for the shadow blur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = None
        self._is_dark = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent; border: none;")

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        fill_color = (
            "#333333" if self._is_dark
            else self._c.get("bg_card_inner", "#f1f5f9")
        )
        p.setBrush(QColor(fill_color))
        radius = float(SettingsGroup.CORNER_RADIUS)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), radius, radius
        )
        p.end()


class _LeadingPill(QWidget):
    """Small colored circle with a translucent halo. Used as a leading
    indicator on rows that carry an identity color (e.g. game path rows
    showing TTR violet or CC blue)."""

    SIZE = 10
    HALO = 2

    def __init__(self, token_name: str, parent=None):
        super().__init__(parent)
        self._token = token_name
        self._resolved_color: str | None = None
        side = self.SIZE + self.HALO * 2
        self.setFixedSize(side, side)

    def apply_theme(self, c, is_dark):
        self._resolved_color = c.get(self._token, "#888888")
        self.update()

    def paintEvent(self, e):
        if self._resolved_color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Halo — 25% alpha of the dot color, full widget size.
        halo = QColor(self._resolved_color)
        halo.setAlpha(64)
        p.setBrush(halo)
        side = self.SIZE + self.HALO * 2
        p.drawEllipse(QRectF(0, 0, side, side))

        # Dot — full-alpha core, centered, SIZE×SIZE.
        p.setBrush(QColor(self._resolved_color))
        p.drawEllipse(QRectF(self.HALO, self.HALO, self.SIZE, self.SIZE))
        p.end()


class _ChevronWidget(QWidget):
    """A small right-pointing triangle that rotates around its center.
    Exposes a `rotation` Qt property (degrees) so it can be animated."""

    SIZE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rotation = 0.0
        self._color = None
        self.setFixedSize(self.SIZE, self.SIZE)

    def _get_rotation(self) -> float:
        return self._rotation

    def _set_rotation(self, value: float):
        self._rotation = float(value)
        self.update()

    rotation = Property(float, _get_rotation, _set_rotation)

    def apply_theme(self, c, is_dark):
        self._color = c.get("text_muted", "#888")
        self.update()

    def paintEvent(self, e):
        if self._color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        p.translate(cx, cy)
        p.rotate(self._rotation)
        # Right-pointing triangle at rotation=0, centered on origin.
        tri = QPolygonF([
            QPointF(-2.5, -3.5),
            QPointF(-2.5,  3.5),
            QPointF( 3.5,  0.0),
        ])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawPolygon(tri)
        p.end()


class _CollapsibleContentClip(QWidget):
    """Fixed-height viewport that clips a full-height settings row container."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content = None
        self._forced_height = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_content_widget(self, widget):
        self._content = widget
        widget.setParent(self)
        self._sync_content_geometry()

    def natural_height(self) -> int:
        if self._content is None or self._content.layout() is None:
            return 0
        return self._content.layout().minimumSize().height()

    def set_forced_height(self, height: int):
        self._forced_height = max(0, int(height))
        self.setMinimumHeight(self._forced_height)
        self.setMaximumHeight(self._forced_height)
        self._sync_content_geometry()
        self.updateGeometry()

    def release_height(self):
        self._forced_height = None
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._sync_content_geometry()
        self.updateGeometry()

    def sizeHint(self):
        return QSize(0, self._height_hint())

    def minimumSizeHint(self):
        return QSize(0, self._height_hint())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_content_geometry()

    def _height_hint(self) -> int:
        if self._forced_height is not None:
            return self._forced_height
        return self.natural_height()

    def _sync_content_geometry(self):
        if self._content is None:
            return
        height = max(self.natural_height(), self.height(), self._height_hint())
        self._content.setGeometry(0, 0, self.width(), height)


class CollapsibleSettingsGroup(SettingsGroup):
    """Section block whose first row is a clickable header (title + chevron).
    Clicking the header toggles visibility of the remaining rows and persists
    the collapsed state via `settings_manager.set(persist_key, bool)`.

    Unlike `SettingsGroup`, the section title is rendered *inside* the block
    as the first row, not above it. This keeps the collapsed state looking
    like a single coherent control instead of an empty section beneath a
    floating title.
    """

    scroll_reserve_changed = Signal(int)

    def __init__(self, title: str, settings_manager, persist_key: str,
                 parent=None):
        # Don't render the title above the block — we own the header instead.
        super().__init__(title="", parent=parent)
        self._title_text = title
        self._settings_manager = settings_manager
        self._persist_key = persist_key
        self._collapsed = bool(
            settings_manager.get(persist_key, True)
        )
        self._collapse_anim = None
        self._chevron_anim = None
        self._animated_content_height = 0
        self._scroll_reserve_base = 0

        self._header = _CollapsibleHeader(title, self._collapsed, self)
        self._header.clicked.connect(self.toggle)

        # The clip animates height while the inner content container keeps its
        # natural row layout. That prevents labels/buttons from being squeezed
        # while the Advanced body opens or closes.
        self._content_clip = _CollapsibleContentClip(self._block)
        self._content_container = QWidget(self._content_clip)
        self._content_container.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._content_clip.set_content_widget(self._content_container)
        self._rows_layout = QVBoxLayout(self._content_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)

        # SettingsGroup.__init__ already installed a QVBoxLayout on self._block
        # for rows. Detach that layout (Qt requires reparenting it to a
        # throwaway widget — you cannot setLayout(None) on a widget that
        # already has a layout). Then install a fresh layout with header + container.
        old_block_layout = self._block.layout()
        if old_block_layout is not None:
            tmp = QWidget()
            tmp.setLayout(old_block_layout)
            tmp.deleteLater()
        block_layout = QVBoxLayout(self._block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(0)
        block_layout.addWidget(self._header)
        block_layout.addWidget(self._content_clip)

        # Apply initial collapsed state to the container.
        if self._collapsed:
            self._content_clip.set_forced_height(0)

    def add_row(self, row):
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._refresh_last_row()
        # If we're collapsed, hide the row so initial layout is right and
        # it doesn't briefly render before the next collapse animation.
        if self._collapsed:
            row.setVisible(False)
        else:
            self._content_clip.release_height()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _get_content_height(self) -> int:
        return self._animated_content_height

    def _set_content_height(self, value: int):
        height = max(0, int(value))
        self._animated_content_height = height
        self._content_clip.set_forced_height(height)
        self._block.updateGeometry()
        self._block_wrapper.updateGeometry()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
        self._emit_scroll_reserve(height)

    content_height = Property(int, _get_content_height, _set_content_height)

    def _content_natural_height(self) -> int:
        # Settings rows declare minimum heights for the polished row rhythm;
        # their Qt sizeHint can be taller/shorter depending on label content.
        # The settled layout uses the minimum height, so animate to that value
        # to avoid a final snap when the fixed animation height is released.
        return self._content_container.layout().minimumSize().height()

    def _release_content_height(self):
        self._content_clip.release_height()
        self._block.updateGeometry()
        self._block_wrapper.updateGeometry()
        self.updateGeometry()

    def _emit_scroll_reserve(self, content_height: int):
        if self._scroll_reserve_base <= 0:
            self.scroll_reserve_changed.emit(0)
            return
        reserve = max(0, self._scroll_reserve_base - content_height)
        self.scroll_reserve_changed.emit(reserve)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._settings_manager.set(self._persist_key, self._collapsed)
        self._header.set_collapsed(self._collapsed)

        # Interrupt any in-flight animation.
        if self._collapse_anim is not None:
            self._collapse_anim.stop()
            self._collapse_anim = None
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0

        # Interrupt any in-flight chevron animation.
        if self._chevron_anim is not None:
            self._chevron_anim.stop()
            self._chevron_anim = None

        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        import utils.motion as motion

        # Resolve target content height. Note: rows must remain visible during
        # a collapse animation, otherwise the layout's preferred height drops
        # to 0 immediately and there's nothing to animate.
        if self._collapsed:
            start_h = self._content_clip.height()
            if start_h <= 0:
                start_h = self._content_natural_height()
            end_h = 0
            self._scroll_reserve_base = start_h
        else:
            # Rows need to be visible during the expand animation so the
            # container has a non-zero sizeHint to animate toward.
            for row in self._rows:
                row.setVisible(True)
            end_h = self._content_natural_height()
            start_h = 0
            self._scroll_reserve_base = 0
            self.scroll_reserve_changed.emit(0)

        # Reduced motion: snap to the final state synchronously.
        if motion.is_reduced():
            self._block_wrapper.set_shadow_live(True)
            if self._collapsed:
                self._set_content_height(0)
                for row in self._rows:
                    row.setVisible(False)
            else:
                self._release_content_height()
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0
            return

        # Animate.
        raw_duration = motion.DURATION_PAGE * motion._TEST_DURATION_SCALE
        duration = 0 if raw_duration == 0.0 else max(1, int(raw_duration))
        self._block_wrapper.set_shadow_live(False)

        anim = QPropertyAnimation(self, b"content_height")
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(start_h)
        anim.setEndValue(end_h)

        def _on_finished():
            # After collapse: hide rows so the layout doesn't reserve space
            # if/when maxHeight is lifted again.
            # After expand: lift the maximumHeight cap so the container can
            # grow if the user resizes or rows are added later.
            if self._collapsed:
                self._set_content_height(0)
                for row in self._rows:
                    row.setVisible(False)
            else:
                self._release_content_height()
            self._block_wrapper.set_shadow_live(True)
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0
            self._collapse_anim = None

        anim.finished.connect(_on_finished)
        self._collapse_anim = anim
        # Pre-set the start value before starting so the first frame is correct.
        self.content_height = start_h
        anim.start()

        # Parallel chevron rotation animation.
        chevron_anim = QPropertyAnimation(self._header._chevron, b"rotation")
        chevron_anim.setDuration(duration)
        chevron_anim.setEasingCurve(QEasingCurve.InOutCubic)
        # Reverse the snap that set_collapsed already applied — start from
        # the previous angle and animate to the new one.
        chevron_anim.setStartValue(90.0 if self._collapsed else 0.0)
        chevron_anim.setEndValue(0.0 if self._collapsed else 90.0)

        def _on_chevron_done():
            self._chevron_anim = None

        chevron_anim.finished.connect(_on_chevron_done)
        self._chevron_anim = chevron_anim
        # Pre-set the start frame so the visual is consistent.
        self._header._chevron.rotation = 90.0 if self._collapsed else 0.0
        chevron_anim.start()

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        self._header.apply_theme(c, is_dark)


class _CollapsibleHeader(QFrame):
    """Clickable header row used inside a `CollapsibleSettingsGroup`.
    Same height as a no-sublabel SettingsRow (48px), with the section title
    on the left and a chevron on the right."""

    clicked = Signal()

    def __init__(self, title: str, collapsed: bool, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        self.setFixedHeight(SettingsRow.HEIGHT_NO_SUB)
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.title_label, 1)

        self._chevron = _ChevronWidget(self)
        self._chevron.rotation = 90.0 if not collapsed else 0.0
        lay.addWidget(self._chevron)

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        # Snap the chevron rotation. The animated case in
        # CollapsibleSettingsGroup.toggle pre-sets this to the start value
        # before starting the animation, then animates over duration.
        self._chevron.rotation = 0.0 if collapsed else 90.0
        self.update()

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; font-style: normal; "
            f"letter-spacing: 0.15px; "
            f"color: {c['text_primary']}; background: transparent; border: none;"
        )
        self._chevron.apply_theme(c, is_dark)
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        if not hasattr(self, "_c"):
            return
        p = QPainter(self)
        # Header hover overlay — slightly stronger than SettingsRow's so this
        # row reads as clickable.
        if self._hovered:
            overlay = QColor("#ffffff" if self._is_dark else "#0f172a")
            overlay.setAlpha(13 if self._is_dark else 15)
            p.fillRect(self.rect(), overlay)
        # Divider only when expanded.
        if not self._collapsed:
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
            w, h = self.width(), self.height()
            p.drawLine(14, h - 1, w - 14, h - 1)
        p.end()


# ── Main Settings Tab ──────────────────────────────────────────────────────────

class SettingsTab(QWidget):
    debug_visibility_changed = Signal(bool)
    theme_changed = Signal()
    input_backend_changed = Signal()
    clear_credentials_requested = Signal()
    max_accounts_changed = Signal(int)

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self._groups = []

        # Scroll area wrapping everything
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        is_dark = resolve_theme(self.settings_manager) == "dark"
        install_modern_scrollbar(scroll, is_dark=is_dark)

        scroll.verticalScrollBar().valueChanged.connect(
            self._maybe_clear_advanced_scroll_reserve
        )

        scroll_inner = QWidget()
        scroll_inner_layout = QHBoxLayout(scroll_inner)
        scroll_inner_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setMaximumWidth(880)
        # Inline the centering pattern: stretches absorb extra space when the
        # window is wider than 880; the high stretch factor on the content
        # widget makes it claim available width up to its maxWidth. Doing
        # this manually instead of via clamp_centered() because that helper
        # uses Qt.AlignHCenter, which makes Qt honor the widget's sizeHint
        # and ignore size policy — fine for the Launch tab whose content
        # has a meaningful sizeHint, but it leaves Settings rows collapsed
        # to ~400px in a 720px window.
        scroll_inner_layout.addStretch(1)
        scroll_inner_layout.addWidget(content, 1000)
        scroll_inner_layout.addStretch(1)
        scroll.setWidget(scroll_inner)

        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(20, 24, 20, 24)
        # Section blocks have internal bottom padding (~18px) for the painted
        # shadow; reduce the layout-level spacing so the visual gap between
        # sections stays similar to before the shadow pass.
        self._main_layout.setSpacing(12)
        self._main_layout.setAlignment(Qt.AlignTop)

        self._build_general_group()
        self._build_games_group()
        self._build_keepalive_group()
        self._build_advanced_group()

        self._main_layout.addStretch()

        self.refresh_theme()

    def _build_general_group(self):
        group = SettingsGroup("General")
        self._groups.append(group)

        # Theme row
        current = self.settings_manager.get("theme", "system")
        theme_idx = ["system", "light", "dark"].index(current)
        self.theme_row = DropdownRow(
            "Appearance",
            ["System", "Light", "Dark"],
            theme_idx
        )
        self.theme_row.index_changed.connect(self.change_theme)
        group.add_row(self.theme_row)

        # Max accounts per game
        saved_max = self.settings_manager.get("max_accounts_per_game", 4)
        max_options = ["4", "5", "6", "7", "8"]
        max_idx = max(0, min(saved_max - 4, len(max_options) - 1))
        self.max_accounts_row = DropdownRow(
            "Max Accounts Per Game",
            max_options,
            max_idx,
            sublabel="How many account slots per game (TTR / CC)"
        )
        self.max_accounts_row.index_changed.connect(self._on_max_accounts_changed)
        group.add_row(self.max_accounts_row)

        # Reduce-motion row (tri-state, behavior unchanged from current code)
        import utils.motion as motion
        motion.set_settings_manager(self.settings_manager)
        explicit = self.settings_manager.get("reduce_motion_set_explicitly", False)
        if not explicit:
            initial_idx = 0  # System default
        elif self.settings_manager.get("reduce_motion", False):
            initial_idx = 1  # On
        else:
            initial_idx = 2  # Off
        sublabel = (
            "System default follows your desktop's reduce-motion setting. "
            "Choose On or Off to override."
        )
        self.reduce_motion_row = DropdownRow(
            "Reduce Motion",
            ["System default", "On", "Off"],
            initial_idx,
            sublabel=sublabel,
        )
        self.reduce_motion_row.index_changed.connect(self._on_reduce_motion_changed)
        group.add_row(self.reduce_motion_row)

        self._main_layout.addWidget(group)

    def _build_games_group(self):
        group = SettingsGroup("Games")
        self._groups.append(group)

        self.ttr_path_row = GamePathRow(
            self.settings_manager,
            settings_key="ttr_engine_dir",
            exe_name_fn=get_engine_executable_name,
            find_path_fn=find_engine_path,
            label="Toontown Rewritten",
        )
        group.add_row(self.ttr_path_row)

        self.cc_path_row = GamePathRow(
            self.settings_manager,
            settings_key="cc_engine_dir",
            exe_name_fn=get_cc_engine_executable_name,
            find_path_fn=find_cc_engine_path,
            label="Corporate Clash",
        )
        group.add_row(self.cc_path_row)

        # Compatibility runtime row — visible only when CC install is
        # configured (read-only) or steam-proton (with Change button).
        # Hidden entirely on Windows.
        self.compat_runtime_row = CompatRuntimeRow(
            settings_manager=self.settings_manager,
            get_active_install=self._get_active_cc_install,
        )
        group.add_row(self.compat_runtime_row)

        self._main_layout.addWidget(group)

    def _build_keepalive_group(self):
        group = SettingsGroup("Keep-Alive")
        self._keepalive_group = group
        self._groups.append(group)

        # Master opt-in toggle — disabled by default. Enabling fires a
        # consent dialog (Task 10) before committing the True value.
        master_initial = bool(self.settings_manager.get("keep_alive_enabled", False))
        self.ka_master_row = ToggleRow(
            "Enable Keep-Alive",
            master_initial,
            sublabel=(
                "Periodically sends a keystroke to keep toons logged in. "
                "Disabled by default. See warning before enabling. "
                "Your previous per-toon Keep-Alive selections are preserved."
            ),
        )
        self.ka_master_row.toggled.connect(self._on_keep_alive_master_toggle)
        group.add_row(self.ka_master_row)

        self._ka_actions = [
            ("Jump", "jump"),
            ("Open / Close Book", "book"),
            ("Move Forward", "up"),
        ]
        saved_action = self.settings_manager.get("keep_alive_action", "jump")
        action_idx = next((i for i, (_, v) in enumerate(self._ka_actions) if v == saved_action), 0)
        self.ka_action_row = DropdownRow(
            "Action",
            [d for d, _ in self._ka_actions],
            action_idx
        )
        self.ka_action_row.index_changed.connect(self._on_keep_alive_action_changed)
        group.add_row(self.ka_action_row)

        delay_options = ["Rapid Fire", "1 sec", "5 sec", "10 sec", "30 sec", "1 min", "3 min", "5 min", "10 min"]
        saved_delay = self.settings_manager.get("keep_alive_delay", "30 sec")
        delay_idx = delay_options.index(saved_delay) if saved_delay in delay_options else 4
        self.ka_delay_row = DropdownRow(
            "Interval",
            delay_options,
            delay_idx,
        )
        self.ka_delay_row.index_changed.connect(self._on_keep_alive_delay_changed)
        group.add_row(self.ka_delay_row)

        # Apply initial ghost state.
        self._refresh_keep_alive_row_enabled_state(master_initial)

        self._main_layout.addWidget(group)

    def _refresh_keep_alive_row_enabled_state(self, master_enabled: bool):
        """Ghost (or un-ghost) the action and interval rows based on the
        master toggle state."""
        self.ka_action_row.setEnabled(master_enabled)
        self.ka_delay_row.setEnabled(master_enabled)

    def _on_keep_alive_master_toggle(self, checked: bool):
        """Handler for the master toggle. On flip-to-on, fire the consent
        dialog and only commit the True value if the user confirms. If the
        user already acknowledged TOS consent during installer setup
        (keep_alive_consent_acknowledged=true), skip the dialog and commit
        directly."""
        if not checked:
            self.settings_manager.set("keep_alive_enabled", False)
            self._refresh_keep_alive_row_enabled_state(False)
            return
        # Toggle was flipped on — confirm before committing, unless the
        # installer already captured informed consent.
        if self.settings_manager.get("keep_alive_consent_acknowledged", False):
            self.settings_manager.set("keep_alive_enabled", True)
            self._refresh_keep_alive_row_enabled_state(True)
            return
        if self._show_keep_alive_warning_dialog():
            self.settings_manager.set("keep_alive_enabled", True)
            self._refresh_keep_alive_row_enabled_state(True)
        else:
            # User cancelled — revert visual without re-firing toggled.
            self.ka_master_row.toggle.blockSignals(True)
            self.ka_master_row.setChecked(False)
            self.ka_master_row.toggle.blockSignals(False)
            # Setting was never written; ghost state stays as it was.

    def _show_keep_alive_warning_dialog(self) -> bool:
        """Show the TOS-aware consent dialog. Returns True if the user
        clicked Enable, False on Cancel/Esc/close.

        Factored as a method so tests can monkeypatch it without invoking
        the real modal."""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Enable Keep-Alive?")
        box.setText(
            "Keep-Alive sends periodic input to your toon windows even while "
            "you are not actively playing.\n\n"
            "Both Toontown Rewritten and Corporate Clash prohibit automation "
            "tools of this kind in their Terms of Service. Use of Keep-Alive, "
            "particularly in public areas of either game, may result in "
            "warnings, account suspension, or permanent termination at the "
            "discretion of those games' moderation teams.\n\n"
            "ToonTown MultiTool is provided as-is and accepts no responsibility "
            "for any consequences arising from its use."
        )
        enable_btn = box.addButton("Enable", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        return box.clickedButton() is enable_btn

    def _get_active_cc_install(self):
        """Return the currently-resolved WineInstall for CC, or None."""
        from services.wine_runtimes import classify_path
        path = self.settings_manager.get("cc_engine_dir", "") if self.settings_manager else ""
        if not path:
            return None
        try:
            return classify_path(path)
        except Exception as e:
            print(f"[settings_tab] classify_path({path!r}) failed: {e}")
            return None

    def _build_advanced_group(self):
        self.advanced_group = CollapsibleSettingsGroup(
            "Advanced", self.settings_manager, "advanced_collapsed"
        )
        self.advanced_group.scroll_reserve_changed.connect(
            self._set_advanced_scroll_reserve
        )
        self._groups.append(self.advanced_group)

        self.companion_row = ToggleRow(
            "TTR Companion App",
            self.settings_manager.get("enable_companion_app", True),
            sublabel="Show toon names and portraits (TTR only)"
        )
        self.companion_row.toggled.connect(self.toggle_companion_app)
        self.advanced_group.add_row(self.companion_row)

        self.debug_row = ToggleRow(
            "Enable Logging",
            self.settings_manager.get("show_debug_tab", False),
        )
        self.debug_row.toggled.connect(self.toggle_debug_tab)
        self.advanced_group.add_row(self.debug_row)

        import sys
        if sys.platform == "win32":
            backend_options = ["Windows API (recommended)"]
            self.settings_manager.set("input_backend", "win32")
            backend_idx = 0
            sublabel = "Native Windows Input"
        else:
            backend_options = ["Xlib (recommended)", "xdotool"]
            current_backend = self.settings_manager.get("input_backend", "xlib")
            if current_backend not in ("xlib", "xdotool"):
                current_backend = "xlib"
                self.settings_manager.set("input_backend", "xlib")
            backend_idx = 0 if current_backend == "xlib" else 1
            sublabel = "Restart required on change"

        self.backend_row = DropdownRow(
            "Input Backend",
            backend_options,
            backend_idx,
            sublabel=sublabel
        )
        self.backend_row.index_changed.connect(self.change_input_backend)
        self.advanced_group.add_row(self.backend_row)

        self.clear_credentials_row = ButtonRow(
            "Clear Stored Credentials",
            sublabel="Delete all saved TTR and CC passwords from Keyring and session memory",
            button_text="Clear",
            destructive=True,
        )
        self.clear_credentials_row.clicked.connect(self._on_clear_credentials_clicked)
        self.advanced_group.add_row(self.clear_credentials_row)

        self._main_layout.addWidget(self.advanced_group)
        self._advanced_scroll_reserve = QWidget()
        self._advanced_scroll_reserve_active = False
        self._advanced_scroll_reserve.setFixedHeight(0)
        self._advanced_scroll_reserve.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._main_layout.addWidget(self._advanced_scroll_reserve)

    def _set_advanced_scroll_reserve(self, height: int):
        if not hasattr(self, "_advanced_scroll_reserve"):
            return
        height = max(0, int(height))
        bar = self._scroll.verticalScrollBar()

        if height > 0:
            if not self._advanced_scroll_reserve_active:
                self._advanced_scroll_reserve_active = (
                    bar.value() >= bar.maximum() - 2
                )
            if self._advanced_scroll_reserve_active:
                self._advanced_scroll_reserve.setFixedHeight(height)
            return

        # When collapse starts at the very bottom, keep the reserve after the
        # body finishes closing. Removing it immediately makes Qt clamp the
        # scrollbar maximum on the final frame, which reads as a judder.
        if (
            self._advanced_scroll_reserve_active
            and self.advanced_group.is_collapsed()
            and self._advanced_scroll_reserve.height() > 0
        ):
            return
        self._clear_advanced_scroll_reserve()

    def _maybe_clear_advanced_scroll_reserve(self):
        if not getattr(self, "_advanced_scroll_reserve_active", False):
            return
        if self.advanced_group._collapse_anim is not None:
            return
        bar = self._scroll.verticalScrollBar()
        if bar.value() < bar.maximum() - 2:
            self._clear_advanced_scroll_reserve()

    def _clear_advanced_scroll_reserve(self):
        if not hasattr(self, "_advanced_scroll_reserve"):
            return
        self._advanced_scroll_reserve_active = False
        self._advanced_scroll_reserve.setFixedHeight(0)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_keep_alive_action_changed(self, i):
        if i < len(self._ka_actions):
            _, value = self._ka_actions[i]
            self.settings_manager.set("keep_alive_action", value)

    def _on_keep_alive_delay_changed(self, i):
        delay = self.ka_delay_row.combo.itemText(i)
        self.settings_manager.set("keep_alive_delay", delay)

    def get_keep_alive_delay_seconds(self) -> float:
        return {
            "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10, "30 sec": 30,
            "1 min": 60, "3 min": 180, "5 min": 300, "10 min": 600
        }.get(self.ka_delay_row.combo.currentText(), 60)

    def highlight_keep_alive_group(self):
        """Scroll the Keep-Alive group into view and run a one-shot pulse
        animation so a user arriving here from the per-slot help affordance
        immediately sees what they came for.

        Safe to call before the tab has been shown — the scroll is a best-
        effort no-op if no enclosing QScrollArea is visible yet, and the
        pulse animation runs on the group widget regardless.
        """
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsColorizeEffect, QScrollArea
        from PySide6.QtGui import QColor

        group = getattr(self, "_keepalive_group", None)
        if group is None:
            return

        # If a previous pulse is still running, stop it first. Otherwise the
        # old animation's `finished` lambda would fire `setGraphicsEffect(None)`
        # on the new effect, killing the new pulse before it starts.
        prior = getattr(self, "_keepalive_highlight_anim", None)
        if prior is not None:
            try:
                prior.stop()
            except RuntimeError:
                # Animation's underlying C++ object may already be deleted
                # via DeleteWhenStopped from a fully-finished previous run.
                pass

        # Best-effort scroll: walk up to the nearest QScrollArea and ensure
        # the group is visible. If no scroll area is found, skip silently.
        widget = group
        while widget is not None:
            parent = widget.parentWidget()
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(group, 0, 24)
                break
            widget = parent

        # 600 ms one-shot accent-blue wash via QGraphicsColorizeEffect.
        from utils.theme_manager import get_theme_colors, is_dark_palette
        c = get_theme_colors(is_dark_palette())
        accent = QColor(c.get("accent_blue_btn", "#0077ff"))

        effect = QGraphicsColorizeEffect(group)
        effect.setColor(accent)
        effect.setStrength(0.0)
        group.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"strength", group)
        anim.setDuration(600)
        anim.setStartValue(0.30)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _cleanup():
            # Drop the effect after the animation so subsequent renders are
            # unmodified.
            group.setGraphicsEffect(None)

        anim.finished.connect(_cleanup)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        # Hold a temporary reference so the animation isn't garbage-collected
        # before it finishes — the animation is parented to `group`, but the
        # extra reference makes the lifetime obvious in code review.
        self._keepalive_highlight_anim = anim

    def change_theme(self, index):
        theme = ["system", "light", "dark"][index]
        self.settings_manager.set("theme", theme)
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self.theme_changed.emit()

    def toggle_companion_app(self, val: bool):
        self.settings_manager.set("enable_companion_app", val)

    def change_input_backend(self, index):
        import sys
        if sys.platform == "win32":
            self.settings_manager.set("input_backend", "win32")
            self.input_backend_changed.emit()
            return

        backend = "xlib" if index == 0 else "xdotool"
        if backend == "xdotool" and self._is_gnome_wayland():
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Warning: xdotool on GNOME Wayland")
            dlg.setIcon(QMessageBox.Warning)
            dlg.setText(
                "xdotool on GNOME Wayland will trigger repeated Remote Desktop "
                "authorization prompts and will likely break input sending.\n\n"
                "Xlib is strongly recommended for GNOME Wayland.\n\n"
                "This will restart the service.\n\nSwitch to xdotool anyway?"
            )
            dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            dlg.setDefaultButton(QMessageBox.Cancel)
            if dlg.exec() != QMessageBox.Ok:
                self.backend_row.combo.blockSignals(True)
                self.backend_row.combo.setCurrentIndex(0)
                self.backend_row.combo.blockSignals(False)
                return
        self.settings_manager.set("input_backend", backend)
        self.input_backend_changed.emit()

    def _is_gnome_wayland(self) -> bool:
        import os
        return (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper())

    def toggle_debug_tab(self, val: bool):
        self.settings_manager.set("show_debug_tab", val)
        self.debug_visibility_changed.emit(val)

    def _on_max_accounts_changed(self, i):
        value = i + 4  # dropdown index 0 = "4", index 4 = "8"
        self.settings_manager.set("max_accounts_per_game", value)
        self.max_accounts_changed.emit(value)

    def _on_reduce_motion_changed(self, idx: int) -> None:
        """Tri-state reduce-motion handler.

        idx 0 → "System default" — clear the explicit override, fall
                back to OS preference.
        idx 1 → "On"  — explicit override, animations always snap.
        idx 2 → "Off" — explicit override, animations always run.
        """
        if idx == 0:
            self.settings_manager.set("reduce_motion_set_explicitly", False)
            self.settings_manager.set("reduce_motion", False)
        elif idx == 1:
            self.settings_manager.set("reduce_motion_set_explicitly", True)
            self.settings_manager.set("reduce_motion", True)
        else:  # idx == 2
            self.settings_manager.set("reduce_motion_set_explicitly", True)
            self.settings_manager.set("reduce_motion", False)

    def _on_clear_credentials_clicked(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Clear Stored Credentials")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            "Are you sure you want to clear all stored TTR and Corporate Clash "
            "account credentials? This will delete them from your system keyring permanently."
        )
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        if dlg.exec() == QMessageBox.Yes:
            self.clear_credentials_requested.emit()

    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")

        # Scroll area background + scrollbar theme.
        for child in self.findChildren(QScrollArea):
            child.setStyleSheet(f"QScrollArea {{ background: {c['bg_app']}; border: none; }}")
            if child.widget():
                child.widget().setStyleSheet(f"background: {c['bg_app']};")
            bar = getattr(child, "_auto_hide_scrollbar", None)
            if bar is not None:
                bar.set_theme(is_dark)

        for group in self._groups:
            group.apply_theme(c, is_dark)

        # Theme custom-painted widgets
        toggle_off = c['bg_input'] if is_dark else '#d1d1d6'
        for toggle in self.findChildren(IOSToggle):
            toggle.set_theme_colors(toggle_off)
