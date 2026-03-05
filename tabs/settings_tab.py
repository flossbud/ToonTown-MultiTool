from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QPoint, QSize, Property
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QCursor, QMouseEvent
from utils.theme_manager import apply_theme, resolve_theme, get_theme_colors

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete"
}


# ── iOS Toggle Switch ──────────────────────────────────────────────────────────

class IOSToggle(QWidget):
    """Animated iOS-style toggle switch."""
    toggled = Signal(bool)

    TRACK_W = 51
    TRACK_H = 31
    THUMB_D = 27
    PADDING = 2

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._thumb_x = float(self.PADDING if not checked else self.TRACK_W - self.THUMB_D - self.PADDING)
        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"thumbX")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_thumb_x(self):
        return self._thumb_x

    def _set_thumb_x(self, val):
        self._thumb_x = val
        self.update()

    thumbX = Property(float, _get_thumb_x, _set_thumb_x)

    def isChecked(self):
        return self._checked

    def setChecked(self, val: bool, animate=False):
        if val == self._checked:
            return
        self._checked = val
        target = float(self.TRACK_W - self.THUMB_D - self.PADDING) if val else float(self.PADDING)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._thumb_x)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._thumb_x = target
            self.update()

    def mousePressEvent(self, e):
        self._checked = not self._checked
        target = float(self.TRACK_W - self.THUMB_D - self.PADDING) if self._checked else float(self.PADDING)
        self._anim.stop()
        self._anim.setStartValue(self._thumb_x)
        self._anim.setEndValue(target)
        self._anim.start()
        self.toggled.emit(self._checked)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Track
        r = self.TRACK_H / 2.0
        track_color = QColor("#34C759") if self._checked else QColor("#3a3a3a")
        # Interpolate color during animation
        if self._thumb_x != self.PADDING and self._thumb_x != (self.TRACK_W - self.THUMB_D - self.PADDING):
            t = (self._thumb_x - self.PADDING) / (self.TRACK_W - self.THUMB_D - 2 * self.PADDING)
            t = max(0.0, min(1.0, t))
            off = QColor("#3a3a3a")
            on  = QColor("#34C759")
            track_color = QColor(
                int(off.red()   + t * (on.red()   - off.red())),
                int(off.green() + t * (on.green() - off.green())),
                int(off.blue()  + t * (on.blue()  - off.blue())),
            )

        p.setPen(Qt.NoPen)
        p.setBrush(track_color)
        from PySide6.QtCore import QRectF
        p.drawRoundedRect(QRectF(0, 0, self.TRACK_W, self.TRACK_H), r, r)

        # Thumb shadow
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(self._thumb_x + 1, self.PADDING + 2, self.THUMB_D, self.THUMB_D))

        # Thumb
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(self._thumb_x, self.PADDING, self.THUMB_D, self.THUMB_D))
        p.end()


# ── iOS Segmented Control ──────────────────────────────────────────────────────

class IOSSegmentedControl(QWidget):
    """iOS-style segmented control for small option sets."""
    index_changed = Signal(int)

    def __init__(self, options: list, parent=None):
        super().__init__(parent)
        self._options = options
        self._index = 0
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"_anim_x")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_x_val = 0.0

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, idx: int):
        self._index = max(0, min(idx, len(self._options) - 1))
        self.update()

    def mousePressEvent(self, e):
        w = self.width() / len(self._options)
        idx = int(e.position().x() / w)
        idx = max(0, min(idx, len(self._options) - 1))
        if idx != self._index:
            self._index = idx
            self.index_changed.emit(idx)
            self.update()

    def paintEvent(self, e):
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        seg_w = w / len(self._options)
        r = 8.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3a3a3a"))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Selected pill
        sx = self._index * seg_w + 2
        p.setBrush(QColor("#636366"))
        p.drawRoundedRect(QRectF(sx, 2, seg_w - 4, h - 4), r - 2, r - 2)

        # Labels
        font = QFont()
        font.setPixelSize(12)
        font.setBold(False)
        p.setFont(font)

        for i, opt in enumerate(self._options):
            x = i * seg_w
            color = QColor("#ffffff") if i == self._index else QColor("#888888")
            p.setPen(color)
            p.drawText(QRectF(x, 0, seg_w, h), Qt.AlignCenter, opt)

        p.end()


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
        text_col.addWidget(self.label_widget)

        if sublabel:
            self.sub_widget = QLabel(sublabel)
            self.sub_widget.setStyleSheet("background: transparent; border: none;")
            text_col.addWidget(self.sub_widget)

        self._layout.addLayout(text_col)
        self._layout.addStretch()

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

        bg = QColor("#3a3a3a") if self._is_dark else QColor("#ffffff")
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
            sep_color = QColor("#555555") if self._is_dark else QColor("#dddddd")
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
                background: {'#4a4a4a' if is_dark else '#f0f0f0'};
                color: {c['text_primary']};
                border: none;
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 13px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {'#3a3a3a' if is_dark else '#ffffff'};
                color: {c['text_primary']};
                selection-background-color: {'#555' if is_dark else '#e0e0e0'};
                border-radius: 8px;
            }}
        """)

    def currentIndex(self):
        return self.combo.currentIndex()

    def setCurrentIndex(self, idx):
        self.combo.setCurrentIndex(idx)

    def findText(self, text):
        return self.combo.findText(text)


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

        content = QWidget()
        scroll.setWidget(content)

        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(20, 24, 20, 24)
        self._main_layout.setSpacing(28)
        self._main_layout.setAlignment(Qt.AlignTop)

        self._build_general_group()
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

        # Show advanced row
        self.advanced_row = ToggleRow(
            "Advanced Settings",
            self.settings_manager.get("show_advanced", False),
            sublabel="Show extra configuration options"
        )
        self.advanced_row.toggled.connect(self.toggle_advanced_visibility)
        group.add_row(self.advanced_row)

        self._main_layout.addWidget(group)

    def _build_keepalive_group(self):
        group = SettingsGroup("Keep-Alive")
        self._groups.append(group)

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

        self._main_layout.addWidget(group)

    def _build_advanced_group(self):
        self.advanced_group = SettingsGroup("Advanced")
        self._groups.append(self.advanced_group)

        self.companion_row = ToggleRow(
            "Companion App",
            self.settings_manager.get("enable_companion_app", True),
            sublabel="Show toon names and portraits"
        )
        self.companion_row.toggled.connect(self.toggle_companion_app)
        self.advanced_group.add_row(self.companion_row)

        self.debug_row = ToggleRow(
            "Show Logs Tab",
            self.settings_manager.get("show_debug_tab", False),
        )
        self.debug_row.toggled.connect(self.toggle_debug_tab)
        self.advanced_group.add_row(self.debug_row)

        backend_options = ["Xlib (recommended)", "xdotool"]
        current_backend = self.settings_manager.get("input_backend", "xlib")
        backend_idx = 0 if current_backend == "xlib" else 1
        self.backend_row = DropdownRow(
            "Input Backend",
            backend_options,
            backend_idx,
            sublabel="Restart required on change"
        )
        self.backend_row.index_changed.connect(self.change_input_backend)
        self.advanced_group.add_row(self.backend_row)
        
        self.clear_credentials_row = SettingsRow(
            "Clear Stored Credentials",
            sublabel="Delete all saved account passwords from Keyring"
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

    def _on_clear_credentials_clicked(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Clear Stored Credentials")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            "Are you sure you want to clear all stored TTR account credentials? "
            "This will delete them from your system keyring permanently."
        )
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        if dlg.exec() == QMessageBox.Yes:
            self.clear_credentials_requested.emit()

    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        bg = "#1c1c1e" if is_dark else "#f2f2f7"
        self.setStyleSheet(f"background: {bg};")

        # Scroll area background
        for child in self.findChildren(QScrollArea):
            child.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
            if child.widget():
                child.widget().setStyleSheet(f"background: {bg};")

        for group in self._groups:
            group.apply_theme(c, is_dark)