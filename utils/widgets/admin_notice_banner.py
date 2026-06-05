"""Non-blocking banner shown on Windows when MultiTool is not running as
administrator, offering a one-click elevated restart. Modeled on UpdateBanner.
The banner only emits signals; persistence of the dismissal is handled by the
MultiToonTool wiring. No em-dashes in user-facing text."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from utils.icon_factory import make_x_icon


BANNER_TEXT = (
    "Some games can run as administrator, which stops MultiTool from moving your "
    "other toons. If your toons will not move together, restart MultiTool as "
    "administrator or start the game without administrator access."
)

_GRADIENT = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
    "stop:0 #7a4a00, stop:1 #b06a00)"
)


class AdminNoticeBanner(QFrame):
    restart_as_admin = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("admin_notice_banner")
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setObjectName("admin_notice_banner_label")
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        self._label.setToolTip(BANNER_TEXT)
        layout.addWidget(self._label, 1)

        self._restart_btn = QPushButton("Restart as administrator")
        self._restart_btn.setObjectName("admin_notice_banner_restart")
        self._restart_btn.setCursor(Qt.PointingHandCursor)
        self._restart_btn.clicked.connect(self.restart_as_admin.emit)
        layout.addWidget(self._restart_btn, 0)

        self._close_btn = QPushButton()
        self._close_btn.setObjectName("admin_notice_banner_close")
        self._close_btn.setIcon(make_x_icon(14, QColor("#ffffff")))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setToolTip("Dismiss")
        self._close_btn.setAccessibleName("Dismiss administrator notice")
        self._close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._close_btn, 0)

        self.apply_theme()
        self._refresh_label()
        self.hide()

    def set_restart_enabled(self, enabled: bool) -> None:
        """Enable/disable the Restart button (disabled while a relaunch is in
        flight, re-enabled if the user cancels the UAC prompt)."""
        self._restart_btn.setEnabled(enabled)

    def _refresh_label(self) -> None:
        # Always elide so the long text can never overflow a narrow window. At a
        # not-yet-laid-out width (<=12px) elidedText returns nothing; resizeEvent
        # repopulates it once the banner has a real width. The full text is always
        # available via the label tooltip.
        fm = QFontMetrics(self._label.font())
        avail = max(0, self._label.width() - 12)
        self._label.setText(fm.elidedText(BANNER_TEXT, Qt.ElideRight, avail))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_label()

    def apply_theme(self, colors: Optional[dict] = None) -> None:
        """Apply banner styling. `colors` accepted for call symmetry with the
        rest of the theme system; the gradient is theme-independent for now."""
        self.setStyleSheet(
            f"""
            QFrame#admin_notice_banner {{
                background: {_GRADIENT};
                border: none;
            }}
            QLabel#admin_notice_banner_label {{
                background: transparent;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#admin_notice_banner_restart {{
                background: rgba(255, 255, 255, 0.18);
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#admin_notice_banner_restart:hover {{
                background: rgba(255, 255, 255, 0.30);
            }}
            QPushButton#admin_notice_banner_restart:disabled {{
                color: rgba(255, 255, 255, 0.5);
            }}
            QPushButton#admin_notice_banner_close {{
                background: transparent;
                border: none;
                padding: 0;
            }}
            QPushButton#admin_notice_banner_close:hover {{
                background: rgba(255, 255, 255, 0.18);
                border-radius: 4px;
            }}
            """
        )

    def _on_close_clicked(self) -> None:
        self.hide()
        self.dismissed.emit()
