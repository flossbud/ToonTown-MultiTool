import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QCheckBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from utils.theme_manager import apply_theme, resolve_theme, get_theme_colors
from utils.shared_widgets import IOSToggle, IOSSegmentedControl
from services.ttr_login_service import find_engine_path, get_engine_executable_name
from services.cc_login_service import find_cc_engine_path, get_cc_engine_executable_name

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete"
}


# ── Settings Row Types ─────────────────────────────────────────────────────────

class SettingsRow(QFrame):
    """Single iOS-style settings row with label + control."""

    def __init__(self, label: str, sublabel: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(52 if not sublabel else 62)
        self._label = label
        self._sublabel = sublabel
        self._is_first = False
        self._is_last = False
        self._hovered = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 0, 16, 0)
        self._layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        self.label_widget.setMinimumWidth(1)
        text_col.addWidget(self.label_widget)

        if sublabel:
            self.sub_widget = QLabel(sublabel)
            self.sub_widget.setStyleSheet("background: transparent; border: none;")
            self.sub_widget.setMinimumWidth(1)
            text_col.addWidget(self.sub_widget)

        self._layout.addLayout(text_col, 1)


    def add_control(self, widget):
        self._layout.addWidget(widget)

    def set_position(self, is_first, is_last):
        self._is_first = is_first
        self._is_last = is_last

    def apply_theme(self, c, is_dark):
        self.label_widget.setStyleSheet(
            f"font-size: 15px; color: {c['text_primary']}; background: transparent; border: none;"
        )
        if hasattr(self, 'sub_widget'):
            self.sub_widget.setStyleSheet(
                f"font-size: 12px; color: {c['text_muted']}; background: transparent; border: none;"
            )
        self._c = c
        self._is_dark = is_dark
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        if not hasattr(self, '_c'):
            return
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = 12.0

        bg = QColor(self._c.get('bg_card_inner', '#3a3a3a'))
        if self._hovered:
            bg = bg.lighter(115) if self._is_dark else bg.darker(103)

        p.setPen(Qt.NoPen)
        p.setBrush(bg)

        if self._is_first and self._is_last:
            p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        elif self._is_first:
            path = QPainterPath()
            path.moveTo(r, 0)
            path.lineTo(w - r, 0)
            path.quadTo(w, 0, w, r)
            path.lineTo(w, h)
            path.lineTo(0, h)
            path.lineTo(0, r)
            path.quadTo(0, 0, r, 0)
            path.closeSubpath()
            p.drawPath(path)
        elif self._is_last:
            path = QPainterPath()
            path.moveTo(0, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h - r)
            path.quadTo(w, h, w - r, h)
            path.lineTo(r, h)
            path.quadTo(0, h, 0, h - r)
            path.lineTo(0, 0)
            path.closeSubpath()
            p.drawPath(path)
        else:
            p.drawRect(QRectF(0, 0, w, h))

        # Separator (not on last row)
        if not self._is_last:
            sep_color = QColor(self._c.get('border_light', '#555555'))
            p.setPen(sep_color)
            p.drawLine(16, h - 1, w, h - 1)

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
        self.combo.setStyleSheet(f"""
            QComboBox {{
                background: {c['btn_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border_muted']};
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 13px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {c['bg_card_inner']};
                color: {c['text_primary']};
                selection-background-color: {c['btn_bg']};
                border-radius: 8px;
            }}
        """)

    def currentIndex(self):
        return self.combo.currentIndex()

    def setCurrentIndex(self, idx):
        self.combo.setCurrentIndex(idx)

    def findText(self, text):
        return self.combo.findText(text)


class GamePathRow(SettingsRow):
    """Reusable game path row — parameterized for TTR, CC, or any future game."""

    def __init__(self, settings_manager, settings_key: str,
                 exe_name_fn, find_path_fn, parent=None):
        super().__init__("Game Path", "Not configured", parent)
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

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        btn_style = f"""
            QPushButton {{
                background-color: {c['btn_bg']};
                color: {c['text_secondary']};
                border: 1px solid {c['border_muted']};
                border-radius: 6px; padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {c['accent_blue']};
                color: {c['text_on_accent']};
                border: 1px solid {c['accent_blue']};
            }}
        """
        self.browse_btn.setStyleSheet(btn_style)
        self.detect_btn.setStyleSheet(btn_style)

    def _refresh_display(self, path: str, error: bool = False):
        if not path:
            self.sub_widget.setText("Not found — click Browse or Auto-detect")
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
        path = self._find_path_fn()
        if path:
            self.settings_manager.set(self._settings_key, path)
            self.settings_manager.set(self._approval_key, "")
            self._refresh_display(path)
        else:
            self._refresh_display("Could not auto-detect — click Browse", error=True)


# ── Section Group ──────────────────────────────────────────────────────────────

class SettingsGroup(QWidget):
    """Groups rows with iOS card style and an optional section header label."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if title:
            self.title_label = QLabel(title.upper())
            self.title_label.setContentsMargins(4, 0, 0, 6)
            layout.addWidget(self.title_label)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        layout.addWidget(self._rows_container)

        self._rows = []

    def add_row(self, row: SettingsRow):
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._update_positions()

    def _update_positions(self):
        for i, row in enumerate(self._rows):
            row.set_position(i == 0, i == len(self._rows) - 1)

    def apply_theme(self, c, is_dark):
        if hasattr(self, 'title_label'):
            self.title_label.setStyleSheet(
                f"font-size: 12px; font-weight: 600; color: {c['text_muted']}; "
                f"background: transparent; letter-spacing: 0.5px;"
            )
        for row in self._rows:
            row.apply_theme(c, is_dark)


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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        from utils.layout import clamp_centered

        scroll_inner = QWidget()
        scroll_inner_layout = QHBoxLayout(scroll_inner)
        scroll_inner_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        clamp_centered(scroll_inner_layout, content, 720)
        scroll.setWidget(scroll_inner)

        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(20, 24, 20, 24)
        self._main_layout.setSpacing(28)
        self._main_layout.setAlignment(Qt.AlignTop)

        self._build_general_group()
        self._build_ttr_path_group()
        self._build_cc_path_group()
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

        # Show advanced row
        self.advanced_row = ToggleRow(
            "Advanced Settings",
            self.settings_manager.get("show_advanced", False),
            sublabel="Show extra configuration options"
        )
        self.advanced_row.toggled.connect(self.toggle_advanced_visibility)
        group.add_row(self.advanced_row)

        self._main_layout.addWidget(group)

    def _build_ttr_path_group(self):
        group = SettingsGroup("Toontown Rewritten")
        self._groups.append(group)

        self.ttr_path_row = GamePathRow(
            self.settings_manager,
            settings_key="ttr_engine_dir",
            exe_name_fn=get_engine_executable_name,
            find_path_fn=find_engine_path,
        )
        group.add_row(self.ttr_path_row)

        self._main_layout.addWidget(group)

    def _build_cc_path_group(self):
        group = SettingsGroup("Corporate Clash")
        self._groups.append(group)

        self.cc_path_row = GamePathRow(
            self.settings_manager,
            settings_key="cc_engine_dir",
            exe_name_fn=get_cc_engine_executable_name,
            find_path_fn=find_cc_engine_path,
        )
        group.add_row(self.cc_path_row)

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
                "Disabled by default — see warning before enabling. "
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
        dialog and only commit the True value if the user confirms."""
        if not checked:
            self.settings_manager.set("keep_alive_enabled", False)
            self._refresh_keep_alive_row_enabled_state(False)
            return
        # Toggle was flipped on — confirm before committing.
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
            "tools of this kind in their Terms of Service. Use of Keep-Alive — "
            "particularly in public areas of either game — may result in "
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

    def _build_advanced_group(self):
        self.advanced_group = SettingsGroup("Advanced")
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
        
        self.clear_credentials_row = SettingsRow(
            "Clear Stored Credentials",
            sublabel="Delete all saved TTR and CC passwords from Keyring and session memory"
        )
        self.clear_credentials_btn = QPushButton("Clear")
        self.clear_credentials_btn.setFixedWidth(80)
        self.clear_credentials_btn.setStyleSheet("""
            QPushButton {
                color: #ff3b30; 
                font-weight: bold; 
                background: transparent;
                border: 1px solid #ff3b30;
                border-radius: 6px;
                padding: 4px;
            }
            QPushButton:hover {
                background: rgba(255, 59, 48, 0.1);
            }
        """)
        self.clear_credentials_btn.setCursor(Qt.PointingHandCursor)
        self.clear_credentials_btn.clicked.connect(self._on_clear_credentials_clicked)
        self.clear_credentials_row.add_control(self.clear_credentials_btn)
        self.advanced_group.add_row(self.clear_credentials_row)

        show = self.settings_manager.get("show_advanced", False)
        self.advanced_group.setVisible(show)
        self._main_layout.addWidget(self.advanced_group)

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

    def toggle_advanced_visibility(self, show: bool):
        self.settings_manager.set("show_advanced", show)
        self.advanced_group.setVisible(show)

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

        # Scroll area background
        for child in self.findChildren(QScrollArea):
            child.setStyleSheet(f"QScrollArea {{ background: {c['bg_app']}; border: none; }}")
            if child.widget():
                child.widget().setStyleSheet(f"background: {c['bg_app']};")

        for group in self._groups:
            group.apply_theme(c, is_dark)

        # Theme custom-painted widgets
        toggle_off = c['bg_input'] if is_dark else '#d1d1d6'
        for toggle in self.findChildren(IOSToggle):
            toggle.set_theme_colors(toggle_off)

        for seg in self.findChildren(IOSSegmentedControl):
            seg.set_theme_colors(
                c['bg_input'], c['btn_bg'],
                c['text_primary'], c['text_muted']
            )
