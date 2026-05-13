import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QFileDialog
)
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from utils.theme_manager import apply_theme, resolve_theme, get_theme_colors
from utils.shared_widgets import IOSToggle
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
            self.button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_bg']};
                    color: {c['text_secondary']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 6px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_blue']};
                    color: {c['text_on_accent']};
                    border: 1px solid {c['accent_blue']};
                }}
            """)


class GamePathRow(SettingsRow):
    """Reusable game path row — parameterized for TTR, CC, or any future game."""

    def __init__(self, settings_manager, settings_key: str,
                 exe_name_fn, find_path_fn, label: str = "Game Path",
                 parent=None):
        super().__init__(label, "Not configured", parent)
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
        path = self._find_path_fn()
        if path:
            self.settings_manager.set(self._settings_key, path)
            self.settings_manager.set(self._approval_key, "")
            self._refresh_display(path)
        else:
            self._refresh_display("Could not auto-detect. Click Browse.", error=True)


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

        self._block = _SectionBlock(self)
        self._rows_layout = QVBoxLayout(self._block)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        layout.addWidget(self._block)

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

    def apply_theme(self, c, is_dark):
        self._c = c
        from utils.theme_manager import apply_card_shadow
        apply_card_shadow(self, is_dark, blur=18, offset_y=4)
        self.update()

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(self._c.get("border_card", "#363636")))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(QColor(self._c.get("bg_card_inner", "#2e2e2e")))
        r = float(SettingsGroup.CORNER_RADIUS)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), r, r
        )
        p.end()


class CollapsibleSettingsGroup(SettingsGroup):
    """Section block whose first row is a clickable header (title + chevron).
    Clicking the header toggles visibility of the remaining rows and persists
    the collapsed state via `settings_manager.set(persist_key, bool)`.

    Unlike `SettingsGroup`, the section title is rendered *inside* the block
    as the first row, not above it. This keeps the collapsed state looking
    like a single coherent control instead of an empty section beneath a
    floating title.
    """

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

        self._header = _CollapsibleHeader(title, self._collapsed, self)
        self._header.clicked.connect(self.toggle)
        # The header lives inside the rounded block as the first child of
        # the rows layout, so the soft-surface fill backs it.
        self._rows_layout.addWidget(self._header)

    def add_row(self, row):
        super().add_row(row)
        row.setVisible(not self._collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle(self):
        self._collapsed = not self._collapsed
        self._settings_manager.set(self._persist_key, self._collapsed)
        self._header.set_collapsed(self._collapsed)
        for row in self._rows:
            row.setVisible(not self._collapsed)

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

        self.chevron_label = QLabel(self._chevron_glyph())
        self.chevron_label.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.chevron_label)

    def _chevron_glyph(self) -> str:
        return "▸" if self._collapsed else "▾"

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        self.chevron_label.setText(self._chevron_glyph())
        self.update()

    def apply_theme(self, c, is_dark):
        self._c = c
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; font-style: normal; "
            f"letter-spacing: 0.15px; "
            f"color: {c['text_primary']}; background: transparent; border: none;"
        )
        self.chevron_label.setStyleSheet(
            f"font-size: 14px; color: {c['text_muted']}; "
            f"background: transparent; border: none;"
        )
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
            is_dark = self._c.get("bg_app", "#1a1a1a") == "#1a1a1a"
            overlay = QColor("#ffffff" if is_dark else "#0f172a")
            overlay.setAlpha(13 if is_dark else 15)
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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

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
        self._main_layout.setSpacing(28)
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

    def _build_advanced_group(self):
        self.advanced_group = CollapsibleSettingsGroup(
            "Advanced", self.settings_manager, "advanced_collapsed"
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
