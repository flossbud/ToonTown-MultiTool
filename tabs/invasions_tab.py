import json
import urllib.request
import threading
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow, SmoothProgressBar,
)


# ── Cog department lookup ──────────────────────────────────────────────────
# Maps cog type name (lowercase) → (dept_label, bg_color, text_color)
_SELLBOT  = ("Sellbot",  "#E05252", "#ffffff")
_CASHBOT  = ("Cashbot",  "#56B8E8", "#ffffff")
_LAWBOT   = ("Lawbot",   "#9B6BE0", "#ffffff")
_BOSSBOT  = ("Bossbot",  "#4CB960", "#ffffff")
_BOARDBOT = ("Boardbot", "#8B6948", "#ffffff")
_UNKNOWN  = ("?",        "#888888", "#ffffff")

COG_DEPT_MAP = {
    # Sellbot
    "cold caller": _SELLBOT, "telemarketer": _SELLBOT, "name dropper": _SELLBOT,
    "glad hander": _SELLBOT, "mover & shaker": _SELLBOT, "two-face": _SELLBOT,
    "the mingler": _SELLBOT, "mr. hollywood": _SELLBOT,
    # Cashbot
    "short change": _CASHBOT, "penny pincher": _CASHBOT, "tightwad": _CASHBOT,
    "bean counter": _CASHBOT, "number cruncher": _CASHBOT, "money bags": _CASHBOT,
    "loan shark": _CASHBOT, "robber baron": _CASHBOT,
    # Lawbot
    "bottom feeder": _LAWBOT, "bloodsucker": _LAWBOT, "double talker": _LAWBOT,
    "ambulance chaser": _LAWBOT, "back stabber": _LAWBOT, "spin doctor": _LAWBOT,
    "legal eagle": _LAWBOT, "big wig": _LAWBOT,
    # Bossbot
    "flunky": _BOSSBOT, "pencil pusher": _BOSSBOT, "yesman": _BOSSBOT,
    "micromanager": _BOSSBOT, "downsizer": _BOSSBOT, "head hunter": _BOSSBOT,
    "corporate raider": _BOSSBOT, "the big cheese": _BOSSBOT,
    # Boardbot
    "con artist": _BOARDBOT, "connoisseur": _BOARDBOT, "swindler": _BOARDBOT,
    "middleman": _BOARDBOT, "toxic manager": _BOARDBOT, "magnate": _BOARDBOT,
    "big fish": _BOARDBOT, "head honcho": _BOARDBOT,
}


def _cog_dept(cog_type: str):
    return COG_DEPT_MAP.get(cog_type.lower(), _UNKNOWN)


def _title_case_cog(name: str) -> str:
    """Title-case a cog name, preserving 'Mr.' and '&'."""
    return " ".join(
        w if w == "&" else w.capitalize()
        for w in name.split()
    )


def _parse_progress(progress_str: str):
    """Parse '1234/5000' into (current, total) or None."""
    try:
        parts = progress_str.split("/")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, AttributeError):
        pass
    return None


class InvasionsWorker(threading.Thread):
    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback

    def run(self):
        try:
            req = urllib.request.Request(
                "https://www.toontownrewritten.com/api/invasions",
                headers={'User-Agent': 'ToonTown MultiTool'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self.callback(data.get("invasions", {}), data.get("error"))
        except Exception as e:
            self.callback({}, str(e))

class InvasionsTab(QWidget):
    invasions_updated = Signal(dict, object)

    def __init__(self, settings_manager=None, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.invasions_updated.connect(self._on_invasions_updated)

        self.build_ui()
        self.refresh_theme()

        if self.settings_manager:
            self.settings_manager.on_change(self._on_setting_changed)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(60000) # 1 minute
        self.refresh_timer.timeout.connect(self.fetch_invasions)
        self.refresh_timer.start()
        self.fetch_invasions()

    def shutdown(self):
        """Stop refresh timer and background threads."""
        self.refresh_timer.stop()

    def _on_setting_changed(self, key, value):
        if key == "theme":
            self.refresh_theme()

    def fetch_invasions(self):
        self.status_label.setText("Fetching invasions...")
        worker = InvasionsWorker(self._worker_callback)
        worker.start()

    def _worker_callback(self, invasions, error):
        self.invasions_updated.emit(invasions, error)

    @Slot(dict, object)
    def _on_invasions_updated(self, invasions, error):
        if error:
            self.status_label.setText(f"Error: {error}")
            return

        self.status_label.setText(f"Last updated: {time.strftime('%I:%M %p')}")

        # Clear layout
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._cards = []
        if not invasions:
            self._show_empty_state()
        else:
            for district, details in invasions.items():
                card = self._create_invasion_card(district, details)
                self.cards_layout.addWidget(card)
                self._cards.append(card)

        self.cards_layout.addStretch()
        self.refresh_theme()

    def _show_empty_state(self):
        """Show a styled empty state when no invasions are active."""
        empty = QFrame()
        empty.setObjectName("empty_state")
        lay = QVBoxLayout(empty)
        lay.setContentsMargins(20, 40, 20, 40)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel("No active invasions")
        icon_lbl.setObjectName("empty_title")
        icon_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon_lbl)

        hint_lbl = QLabel("Check back soon — invasions update every minute")
        hint_lbl.setObjectName("empty_hint")
        hint_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint_lbl)

        self.cards_layout.addWidget(empty)
        self._cards.append(empty)

    def _create_invasion_card(self, district, details):
        cog_type = details.get("type", "Unknown Cog").replace("\x03", "")
        dept_label, dept_bg, dept_text = _cog_dept(cog_type)
        progress_str = details.get("progress", "")
        progress_parsed = _parse_progress(progress_str)

        frame = QFrame()
        frame.setObjectName("invasion_card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        # Top row: dept badge + cog name + progress text
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        dept_badge = QLabel(dept_label)
        dept_badge.setAlignment(Qt.AlignCenter)
        dept_badge.setFixedHeight(22)
        dept_badge.setStyleSheet(f"""
            QLabel {{
                background: {dept_bg};
                color: {dept_text};
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 0 6px;
            }}
        """)
        top_row.addWidget(dept_badge)

        cog_lbl = QLabel(_title_case_cog(cog_type))
        cog_lbl.setObjectName("cog_name")
        top_row.addWidget(cog_lbl)

        top_row.addStretch()

        prog_lbl = QLabel(progress_str)
        prog_lbl.setObjectName("progress_text")
        prog_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_row.addWidget(prog_lbl)

        lay.addLayout(top_row)

        # Progress bar (if parseable)
        if progress_parsed:
            current, total = progress_parsed
            bar = SmoothProgressBar()
            bar.setFixedHeight(5)
            bar.set_progress(current / total if total > 0 else 0)
            bar.set_fill_color(dept_bg)
            bar.setObjectName("invasion_bar")
            lay.addWidget(bar)

        # Bottom row: District & elapsed time
        bot_row = QHBoxLayout()
        dist_lbl = QLabel(district)
        dist_lbl.setObjectName("district_name")

        started = details.get("startTimestamp", 0)
        time_lbl = QLabel("")
        time_lbl.setObjectName("time_ago")
        if started > 0:
            elapsed = int(time.time()) - started
            mins = elapsed // 60
            time_lbl.setText(f"{mins} min ago")

        bot_row.addWidget(dist_lbl)
        bot_row.addStretch()
        bot_row.addWidget(time_lbl)
        lay.addLayout(bot_row)

        return frame

    def build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("inv_header")
        header.setFixedHeight(50)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Active Invasions")
        title.setObjectName("inv_title")
        h_lay.addWidget(title)

        h_lay.addStretch()
        self.status_label = QLabel("Initializing...")
        self.status_label.setObjectName("inv_status")
        h_lay.addWidget(self.status_label)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(28)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setObjectName("inv_refresh_btn")
        self.refresh_btn.clicked.connect(self.fetch_invasions)
        h_lay.addWidget(self.refresh_btn)

        outer.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("""
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.15); border-radius: 3px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.25); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        self.scroll_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.scroll_widget)
        self.cards_layout.setContentsMargins(16, 12, 16, 16)
        self.cards_layout.setSpacing(8)
        self.scroll.setWidget(self.scroll_widget)
        outer.addWidget(self.scroll)

        self._cards = []

    def refresh_theme(self):
        c = get_theme_colors(resolve_theme(self.settings_manager) == "dark")
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self.scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

        # Header
        for lbl in self.findChildren(QLabel, "inv_title"):
            lbl.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {c['text_primary']}; "
                f"background: transparent; border: none;"
            )
        self.status_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_muted']}; background: transparent; border: none;"
        )

        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['btn_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {c['btn_border']};
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 0 10px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn']};
                    color: white;
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)

        # Invasion cards
        card_style = f"""
            QFrame#invasion_card {{
                background: {c['bg_card_inner']};
                border: 1px solid {c['border_muted']};
                border-radius: 10px;
            }}
        """
        for card in self._cards:
            if card.objectName() == "invasion_card":
                card.setStyleSheet(card_style)
                apply_card_shadow(card, is_dark)

                for lbl in card.findChildren(QLabel, "cog_name"):
                    lbl.setStyleSheet(
                        f"font-size: 13px; font-weight: bold; color: {c['text_primary']}; "
                        f"background: none; border: none;"
                    )
                for lbl in card.findChildren(QLabel, "progress_text"):
                    lbl.setStyleSheet(
                        f"font-size: 11px; color: {c['text_secondary']}; "
                        f"background: none; border: none;"
                    )
                for lbl in card.findChildren(QLabel, "district_name"):
                    lbl.setStyleSheet(
                        f"font-size: 11px; color: {c['text_secondary']}; "
                        f"background: none; border: none;"
                    )
                for lbl in card.findChildren(QLabel, "time_ago"):
                    lbl.setStyleSheet(
                        f"font-size: 11px; color: {c['text_muted']}; "
                        f"background: none; border: none;"
                    )
                for bar in card.findChildren(SmoothProgressBar):
                    bar.set_bg_color(c['border_muted'])

            elif card.objectName() == "empty_state":
                card.setStyleSheet(
                    f"QFrame#empty_state {{ background: {c['bg_card_inner']}; "
                    f"border: 1px solid {c['border_muted']}; border-radius: 10px; }}"
                )
                for lbl in card.findChildren(QLabel, "empty_title"):
                    lbl.setStyleSheet(
                        f"font-size: 14px; font-weight: 600; color: {c['text_secondary']}; "
                        f"background: none; border: none;"
                    )
                for lbl in card.findChildren(QLabel, "empty_hint"):
                    lbl.setStyleSheet(
                        f"font-size: 11px; color: {c['text_muted']}; "
                        f"background: none; border: none;"
                    )
